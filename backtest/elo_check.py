"""The Elo component check (brief section 7): `python -m backtest.elo_check`.

Walks forward over the seasons in backtest/config.yaml, calling the model only through
`elo_ratings` and `elo_goals` and reading results only through `load_as_of` in backtest mode.
Scores the goals and clean-sheet calibration, the log-loss against a no-skill baseline and
the ratings against upstream Elo; runs the leakage checks; writes
backtest/reports/{date}.md. Exits non-zero, without a report, on any unexpected exception.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from backtest.elo_data import (
    ModelFn,
    SkipLog,
    baseline_pool,
    implied_coefficients,
    match_results,
    rating_pairs,
    read_stability,
    score_gameweek,
    team_results,
)
from backtest.elo_leakage import after_as_of_case, peeking_goals, within_gameweek_case
from backtest.elo_metrics import league_means, poisson_nll
from backtest.elo_report import render
from backtest.elo_summary import group_summary, ratings_table, split_groups, verdict
from backtest.perturb import Corruption, copy_upstream
from fpl.features import load_as_of
from fpl.ingest import ROOT, load_config, upstream_data_dir
from fpl.models.elo import MissingSeedError, elo_ratings
from fpl.models.team_goals import InsufficientSampleError, elo_goals

log = logging.getLogger(__name__)

SETTINGS = Path(__file__).with_name("config.yaml")
ERRORS: dict[str, type[Exception]] = {"MissingSeedError": MissingSeedError,
                                      "InsufficientSampleError": InsufficientSampleError}


@dataclass(frozen=True)
class Models:
    """The public functions under test (swappable in tests)."""

    elo_ratings: ModelFn = elo_ratings
    elo_goals: ModelFn = elo_goals


def load_settings(path: Path = SETTINGS) -> dict:
    """backtest/config.yaml."""
    with Path(path).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def expected_skips(s: dict) -> dict[str, dict[str, dict[int, type[Exception]]]]:
    """The reads that raise by design, with exception names resolved to the model's classes."""
    return {fn: {season: {int(g): ERRORS[name] for g, name in by_gw.items()}
                 for season, by_gw in by_season.items()}
            for fn, by_season in s["expected_skips"].items()}


def _seasons(s: dict) -> list[tuple[str, int, int]]:
    return [(x["id"], int(x["target_gameweeks"][0]), int(x["target_gameweeks"][1]))
            for x in s["seasons"]]


def final_tables(s: dict) -> dict[str, dict[str, pd.DataFrame]]:
    """Each season read at its last target gameweek: the actual results and club names."""
    return {x: load_as_of(x, hi, s["mode"]) for x, _, hi in _seasons(s)}


def _score_season(s: dict, models: Models, skips: SkipLog, finals: dict, season: str,
                  gws: range, prem: str, pools: dict) -> tuple[list, dict]:
    fx = finals[season]["fact_fixture"]
    results = team_results(fx, prem)
    names = finals[season]["dim_team"].set_index("team_id").name
    order = [x for x, _, _ in _seasons(s)]
    parts, reads = [], {}
    for g in gws:
        preds = skips.call("elo_goals", models.elo_goals, season, g - 1, s["mode"])
        if preds is None:
            continue
        reads[(season, g - 1)] = preds
        rows = score_gameweek(preds, results, fx, g, prem)
        home, away = league_means(baseline_pool(pools, order, season, g,
                                                int(s["baseline_pool_seasons"])))
        parts.append(rows.assign(team_name=rows.team_id.map(names),
                                 base_for=np.where(rows.home, home, away)))
    return parts, reads


def collect_goals(s: dict, models: Models, skips: SkipLog, finals: dict,
                  prem: str) -> tuple[pd.DataFrame, dict]:
    """Every scored team-fixture with both log-losses, and the raw predictions by as-of."""
    pools = {x: match_results(finals[x]["fact_fixture"], prem) for x in finals}
    parts, reads = [], {}
    for season, lo, hi in _seasons(s):
        p, r = _score_season(s, models, skips, finals, season, range(lo, hi + 1), prem, pools)
        parts += p
        reads |= r
    df = pd.concat(parts, ignore_index=True)
    df["nll_model"] = poisson_nll(df.lambda_for.to_numpy(), df.goals_for.to_numpy())
    df["nll_base"] = poisson_nll(df.base_for.to_numpy(), df.goals_for.to_numpy())
    return df, reads


def collect_ratings(s: dict, models: Models, skips: SkipLog, finals: dict,
                    prem: str) -> tuple[pd.DataFrame, dict, int]:
    """Rating pairs for the ratings season, every as-of read by season, and non-league rows."""
    reads: dict[str, dict[int, pd.DataFrame]] = {}
    non_league = 0
    for season, lo, hi in _seasons(s):
        fx = finals[season]["fact_fixture"]
        league = set(fx.match_id[fx.tournament == prem])
        reads[season] = {}
        for g in range(max(lo, 1), hi + 1):
            r = skips.call("elo_ratings", models.elo_ratings, season, g, s["mode"])
            if r is not None:
                reads[season][g] = r
                non_league += int((~r.match_id[r.season == season].isin(league)).sum())
    rs = s["ratings"]["season"]
    names = finals[rs]["dim_team"].set_index("team_id").name
    pairs = pd.concat([rating_pairs(r, finals[rs]["fact_fixture"], g, prem)
                       for g, r in reads[rs].items()], ignore_index=True)
    return pairs.assign(team_name=pairs.team_id.map(names)), reads, non_league


def claims_table(goal_reads: dict, rating_reads: dict) -> pd.DataFrame:
    """Brief 6.2's claims, checked at every as-of with both a goals and a ratings read."""
    rows = [{"season": x, "as_of": a, **implied_coefficients(p, rating_reads[x][a], x)}
            for (x, a), p in sorted(goal_reads.items()) if a in rating_reads.get(x, {})]
    return pd.DataFrame(rows)


def run_leakage(s: dict, models: Models, pcfg: dict, src: Path) -> dict:
    """The perturbation and within-gameweek cases on a scratch copy of the upstream data."""
    p = s["perturbation"]
    c = Corruption(tuple(p["score_range"]), tuple(p["elo_range"]), tuple(p["xg_range"]),
                   pcfg["premier_league_tag"], int(pcfg["loader"]["deadline_offset_minutes"]))
    rng = np.random.default_rng(int(p["seed"]))
    fns = {"elo_ratings": models.elo_ratings, "elo_goals": models.elo_goals,
           "planted_leak": peeking_goals}
    with tempfile.TemporaryDirectory(prefix="elo_check_") as tmp:
        dst = Path(tmp) / "data"
        copy_upstream(src, dst, [x for x, _, _ in _seasons(s)], s["upstream_files"])
        cfg = {**pcfg, "upstream": {**pcfg["upstream"], "checkout_path": tmp, "data_dir": "data"}}
        after = [after_as_of_case(fns, k["season"], int(k["as_of"]), src, dst, cfg, rng, c,
                                  s["mode"]) for k in p["cases"]]
        within = [within_gameweek_case(models.elo_ratings, k["season"], int(k["gw"]), src, dst,
                                       cfg, rng, c, s["mode"]) for k in p["within_gameweek"]]
    return {"after": after, "within": within}


def criteria(rt: pd.DataFrame, pooled: dict, leak: dict, stability: dict, s: dict) -> dict:
    """Whether each gate criterion is met (`elo_summary.CRITERIA`)."""
    want = {g for lo, hi in s["ratings"]["pass_gameweeks"] for g in range(lo, hi + 1)}
    marked = rt[rt.mark == "pass mark"]
    honest = [v["changed"] for case in leak["after"] for k, v in case["functions"].items()
              if k != "planted_leak"]
    return {
        "ratings": set(marked.gw) == want and bool(marked.passed.all()),
        "goals": pooled["goals_ok"], "clean_sheets": pooled["cs_ok"],
        "log_loss": pooled["beats_baseline"],
        "perturbation": all(n == 0 for n in honest),
        "planted_leak_caught": all(c["functions"]["planted_leak"]["changed"] > 0
                                   for c in leak["after"]),
        "within_gameweek": all(w["changed"] == 0 and w["control_changed"] > 0
                               for w in leak["within"]),
        "read_stability": all(v["changed"] == v["missing"] == v["extra"] == 0
                              for v in stability.values()),
    }


def run_check(s: dict, models: Models, pcfg: dict, src: Path) -> dict:
    """The whole check; returns everything the report needs."""
    prem = pcfg["premier_league_tag"]
    skips = SkipLog(expected_skips(s))
    finals = final_tables(s)
    goals, goal_reads = collect_goals(s, models, skips, finals, prem)
    pairs, rating_reads, non_league = collect_ratings(s, models, skips, finals, prem)
    stability = {x: read_stability(r, x) for x, r in rating_reads.items() if r}
    leak = run_leakage(s, models, pcfg, src)
    groups = {k: group_summary(v, s) for k, v in split_groups(goals, s).items() if len(v)}
    rt = ratings_table(pairs, s)
    met = criteria(rt, groups[f"Pooled, GW{int(s['pass_from_gw'])} on"], leak, stability, s)
    ok, missed = verdict(met)
    return {"settings": s, "goals": goals, "pairs": pairs, "ratings": rt, "groups": groups,
            "claims": claims_table(goal_reads, rating_reads), "stability": stability,
            "leakage": leak, "skips": skips, "non_league_rows": non_league, "met": met,
            "passed": ok, "missed": missed}


def _git(*args: str) -> str:
    res = subprocess.run(["git", *args], capture_output=True, text=True, check=True)
    return res.stdout.strip()


def run_info(pcfg: dict, root: Path = ROOT) -> dict[str, str]:
    """The code and data under test: commits, model-path cleanliness and config hashes."""
    checkout = root / pcfg["upstream"]["checkout_path"]
    model_yaml = root / "config" / "model.yaml"
    version = (yaml.safe_load(model_yaml.read_text(encoding="utf-8")) or {}).get("model_version")
    dirty = _git("-C", str(root), "status", "--porcelain", "--untracked-files=no", "--",
                 "src/fpl", "config")
    return {
        "commit": _git("-C", str(root), "rev-parse", "HEAD"),
        "code_clean": "yes" if not dirty else f"no: {dirty}",
        "model_version": str(version) if version else "unset",
        "upstream_commit": _git("-C", str(checkout), "rev-parse", "HEAD"),
        "upstream_time": _git("-C", str(checkout), "log", "-1", "--format=%cI"),
        "model_yaml_sha256": hashlib.sha256(model_yaml.read_bytes()).hexdigest(),
        "settings_sha256": hashlib.sha256(SETTINGS.read_bytes()).hexdigest(),
    }


def main() -> int:
    """Run the check on the real upstream checkout and write the dated report."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    start = time.monotonic()
    s = load_settings()
    pcfg = load_config(ROOT / "config" / "pipeline.yaml")
    info = run_info(pcfg) | {"date": f"{datetime.now(UTC):%Y-%m-%d}"}
    results = run_check(s, Models(), pcfg, upstream_data_dir(pcfg, ROOT))
    out = ROOT / s["report_dir"] / f"{info['date']}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(results, info), encoding="utf-8")
    log.info("verdict %s; report %s; %.0f s", "PASS" if results["passed"] else "FAIL", out,
             time.monotonic() - start)
    return 0


if __name__ == "__main__":
    sys.exit(main())
