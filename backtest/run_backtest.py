"""The xP walk-forward backtest (brief section 7): `python -m backtest.run_backtest`.

For each target gameweek g of each configured season, every predictor is called with as-of
g-1 in backtest mode, exactly as the live pipeline calls it: the three baselines (from one
`load_as_of` read, `xp_inputs.baselines`), the model through `xp_backtest.model` and the
components through `xp_backtest.components` (each "module:function", taking `(season,
as_of_gw, mode)`). All are scored on the identical evaluation set against `fact_player_gw`
points for g. A gameweek any predictor can't predict (a read that raises by design) is left
out for all of them. Then the leakage checks, the snapshot-timing audit and the report.

A holdout season (`holdout_seasons`, 2026/27) is refused unless `--holdout` is given; that
look must be approved by Josh and logged in docs/decisions.md first.
"""

from __future__ import annotations

import argparse
import functools
import logging
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.elo_check import corruption, load_settings
from backtest.elo_data import SkipLog
from backtest.perturb import Redirect, copy_upstream, redirect
from backtest.perturb_files import file_rules
from backtest.provenance import report_path, run_info
from backtest.snapshot_timing import deadlines, snapshot_timing
from backtest.xp_components import minutes_summary, player_rows, team_rows
from backtest.xp_eval import actuals, evaluation_rows, model_column
from backtest.xp_inputs import baselines, long_min_minutes, read
from backtest.xp_leakage import peeking_baselines, perturbation_case, refit_findings
from backtest.xp_metrics import bin_table
from backtest.xp_reads import static_findings
from backtest.xp_settings import (
    Predictors,
    check_components,
    check_holdout,
    config_hashes,
    expected_skips,
    load_predictors,
)
from backtest.xp_summary import gate_dry_run, headline, ranking, weakest_groups, windows
from fpl.ingest import ROOT, load_config, upstream_data_dir

log = logging.getLogger(__name__)

ModelFn = Callable[[str, int, str], pd.DataFrame]
Timing = Callable[[dict, dict], pd.DataFrame]
BASELINES = ["ep_next", "last5", "ppg"]
def _seasons(s: dict) -> list[tuple[str, int, int]]:
    return [(x["id"], int(x["target_gameweeks"][0]), int(x["target_gameweeks"][1]))
            for x in s["seasons"]]


def _europe(final: dict, tournaments: list[str]) -> set[int]:
    fx = final["fact_fixture"]
    eu = fx[fx.tournament.isin(tournaments)]
    return {int(t) for t in pd.concat([eu.home_team_id, eu.away_team_id]).dropna()}


def _components(preds: Predictors, s: dict, skips: SkipLog, season: str, g: int,
                rows: pd.DataFrame, final: dict, europe: set[int], into: dict) -> None:
    for name, fn in preds.components.items():
        out = skips.call(name, fn, season, g - 1, s["mode"])
        if out is None:
            continue
        c = s["components"][name]
        part = (team_rows(out, g, final, c["column"], europe) if c["kind"] == "team" else
                player_rows(out, g, rows, final, c["column"], c["outcome"], europe,
                            long_min_minutes()))
        into.setdefault(name, []).append(part.assign(season=season))


def collect(s: dict, preds: Predictors, prem: str, skips: SkipLog) -> dict:
    """Walk forward: the scored rows, per-gameweek counts, component rows, model outputs by
    as-of (for the refit check) and each season's final read."""
    base = functools.partial(baselines, s=s, prem=prem)
    scored, counts, comps, outputs, finals = [], [], {}, {}, {}
    for season, lo, hi in _seasons(s):
        final = finals[season] = read(season, hi, s["mode"])
        europe = _europe(final, s["diagnostics"]["europe_tournaments"])
        for g in range(lo, hi + 1):
            frame = skips.call("baselines", base, season, g - 1, s["mode"])
            out = skips.call("model", preds.model, season, g - 1, s["mode"]) \
                if preds.model else None
            if frame is None or (preds.model and out is None):
                continue
            if preds.model:
                frame = frame.assign(model=model_column(out, frame, s["model"]["column"]).values)
                outputs.setdefault(season, {})[g - 1] = out
            rows, n = evaluation_rows(frame, actuals(final, g))
            scored.append(rows.assign(season=season))
            counts.append({"season": season, "gw": g, **n,
                           "ambiguous": int(rows.ambiguous.sum()),
                           "ep_next_null": int(rows.ep_next_null.sum())})
            _components(preds, s, skips, season, g, rows, final, europe, comps)
    return {"scored": pd.concat(scored, ignore_index=True), "counts": pd.DataFrame(counts),
            "components": {k: pd.concat(v, ignore_index=True) for k, v in comps.items()},
            "outputs": outputs, "finals": finals}


def run_leakage(s: dict, fns: dict[str, ModelFn], honest: list[str], pcfg: dict, src: Path,
                point: Redirect) -> dict:
    """The perturbation cases on a scratch copy of the upstream data, and the static check."""
    p = s["perturbation"]
    c = corruption({"perturbation": p}, pcfg)
    rng = np.random.default_rng(int(p["seed"]))
    files = list(p["files"])
    with tempfile.TemporaryDirectory(prefix="xp_backtest_") as tmp:
        dst = Path(tmp) / "data"
        copy_upstream(src, dst, sorted({k["season"] for k in p["cases"]}), files)
        cases = [perturbation_case(fns, k["season"], int(k["as_of"]), src, dst, point, rng, c,
                                   file_rules(p["files"]), s["mode"], files, controls=honest,
                                   forbid=[src, ROOT / "data"])
                 for k in p["cases"]]
    sc = s["static_check"]
    paths = sorted({f for g in sc["paths"] for f in ROOT.glob(g)})
    static, scanned = static_findings(paths, sc["forbidden"], sc["follow"], sc["trusted"])
    return {"cases": cases, "static": static,
            "static_paths": [str(x.relative_to(ROOT.resolve())) if x.is_relative_to(
                ROOT.resolve()) else str(x) for x in scanned]}


def leakage_met(leak: dict, honest: list[str], refit: dict) -> dict[str, bool]:
    """Whether each leakage criterion holds: no honest change, the planted leak caught, the
    copy reached by every honest function, no static finding, no frozen forecast."""
    cases = leak["cases"]
    return {
        "perturbation": all(c["functions"][f]["changed"] == 0 and not c["functions"][f]["error"]
                            for c in cases for f in honest),
        "planted_leak_caught": bool(cases) and all(
            (c["functions"].get("planted_leak", {}).get("changed") or 0) > 0 for c in cases),
        "copy_reached": all((c["control"][f]["changed"] or 0) > 0 for c in cases for f in honest),
        "static": not leak["static"],
        "refit": not any(v["frozen"] for v in refit.values()),
    }


def summarise(s: dict, scored: pd.DataFrame, preds: list[str],
              late: set[tuple[str, int]]) -> dict:
    """Per reporting window: headline errors, ranking per predictor and calibration."""
    m = s["metrics"]
    out = {}
    for name, df in windows(scored, tuple(s["early_season_gws"]), late).items():
        if df.empty:
            continue
        out[name] = {"headline": headline(df, preds),
                     "ranking": {p: ranking(df, p, int(m["top_n"])) for p in preds},
                     "calibration": {p: bin_table(df[p], df.points, m["calibration_edges"])
                                     for p in preds}}
    return out


def _component_summaries(s: dict, comps: dict) -> dict:
    d = s["diagnostics"]
    out = {}
    for name, rows in comps.items():
        c = s["components"][name]
        out[name] = {"rows": rows, "bins": bin_table(rows.pred, rows.outcome, d[c["edges"]])}
        if c["outcome"] == "p60":
            out[name]["summary"] = minutes_summary(rows)
    return out


def default_timing(pcfg: dict) -> Timing:
    """The snapshot-timing hook `run` uses unless given one: `checkout_timing` on the
    upstream checkout named in `pcfg`."""
    return functools.partial(checkout_timing, pcfg=pcfg)


def checkout_timing(s: dict, finals: dict, *, pcfg: dict) -> pd.DataFrame:
    """The snapshot-timing audit of each season's target gameweeks, from the upstream
    checkout's git history (`snapshot_timing`)."""
    t = s["snapshot_timing"]
    parts = []
    for season, lo, hi in _seasons(s):
        dl = deadlines(finals[season]["fact_fixture"], pcfg["premier_league_tag"],
                       int(pcfg["loader"]["deadline_offset_minutes"]))
        parts.append(snapshot_timing(ROOT / pcfg["upstream"]["checkout_path"],
                                     pcfg["upstream"]["data_dir"], season, dl,
                                     range(lo - 1, hi), t["fields"], float(t["late_share"]))
                     .assign(season=season))
    return pd.concat(parts, ignore_index=True)


def run(s: dict, preds: Predictors, pcfg: dict, src: Path, *, point: Redirect = redirect,
        timing: Timing | None = None, allow_holdout: bool = False) -> dict:
    """The whole backtest; returns everything the report needs. `point` and `timing` are
    swappable for tests (the defaults are the loader's data copy and the git audit)."""
    check_holdout(s, allow_holdout)
    check_components(s)
    prem = pcfg["premier_league_tag"]
    skips = SkipLog(expected_skips(s))
    data = collect(s, preds, prem, skips)
    names = BASELINES + (["model"] if preds.model else [])
    honest = ["baselines", *(["model"] if preds.model else []), *preds.components]
    fns = {"baselines": functools.partial(baselines, s=s, prem=prem),
           **({"model": preds.model} if preds.model else {}), **preds.components,
           "planted_leak": functools.partial(peeking_baselines, s=s, prem=prem)}
    leak = run_leakage(s, fns, honest, pcfg, src, point)
    refit = {x: dict(zip(("frozen", "pairs"), refit_findings(o, s["model"]["column"]),
                         strict=True)) for x, o in data["outputs"].items()}
    met = leakage_met(leak, honest, refit)
    tm = (timing or default_timing(pcfg))(s, data["finals"])
    late = {(r.season, int(r.target)) for r in tm.itertuples() if r.late}
    edges = s["metrics"]["calibration_edges"]
    gate = {p: gate_dry_run(data["scored"], p, s["gate"], edges, all(met.values()))
            for p in (["model"] if preds.model else ["last5", "ppg"])}
    weakest = {p: weakest_groups(data["scored"], p, s["weakest"]) for p in names}
    return {"settings": s, "predictors": names, "scored": data["scored"],
            "deadline_offset_minutes": int(pcfg["loader"]["deadline_offset_minutes"]),
            "counts": data["counts"], "summary": summarise(s, data["scored"], names, late),
            "components": _component_summaries(s, data["components"]),
            "component_names": list(s["components"]),
            "leakage": leak, "refit": refit, "leakage_met": met, "timing": tm, "gate": gate,
            "weakest": weakest, "skips": skips}


def main(argv: list[str] | None = None) -> int:
    """Run on the real upstream checkout and write the dated report."""
    from backtest.xp_report import render

    ap = argparse.ArgumentParser(prog="python -m backtest.run_backtest", description=__doc__)
    ap.add_argument("--baselines-only", action="store_true",
                    help="score the three baselines only, without the model or components")
    ap.add_argument("--holdout", action="store_true",
                    help="allow the holdout seasons (only after Josh's logged approval)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    start = time.monotonic()
    s = load_settings()["xp_backtest"]
    pcfg = load_config(ROOT / "config" / "pipeline.yaml")
    # ROOT follows the imported `fpl`, so record where it came from: a run from another
    # checkout must not silently test this one's code.
    info = run_info(pcfg) | config_hashes() | {"fpl_imported_from": str(ROOT / "src" / "fpl"),
                             "date": f"{datetime.now(UTC):%Y-%m-%d}"}
    results = run(s, load_predictors(s, args.baselines_only), pcfg, upstream_data_dir(pcfg, ROOT),
                  allow_holdout=args.holdout)
    folder = ROOT / "backtest" / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{info['date']}-{s['report_suffix']}" if args.baselines_only else info["date"]
    out = report_path(folder, stem)
    out.write_text(render(results, info), encoding="utf-8")
    log.info("report %s; %.0f s", out, time.monotonic() - start)
    return 0


if __name__ == "__main__":
    sys.exit(main())
