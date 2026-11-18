"""The outside-source Elo check (brief section 7): `python -m backtest.beyondelo_check`.

Compares our Elo ratings (`outputs/elo_ratings.csv`) with beyondELO's (`ext_beyondelo`, read
through `fpl.beyondelo.load_beyondelo`) by predictive log-loss of the match result, with
results read through `load_as_of` in backtest mode. Each source gets its own ordered logistic
fit on the fit window, and both are scored on the scored windows in backtest/config.yaml
(`beyondelo_check`). Writes backtest/reports/{date}-beyondelo.md. Stops with a plain message,
and writes no report, when a match in a window lacks a partner or a fit has no finite answer.

The configured 2026/27 window is a holdout look: run this only with Josh's approval, logged
in docs/decisions.md first (CONTEXT.md, Holdout look).
"""

from __future__ import annotations

import hashlib
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from backtest.beyondelo_data import (
    PARTNERS,
    CheckError,
    Window,
    rank_disagreements,
    ranking_by_gameweek,
    window_table,
)
from backtest.beyondelo_fit import FitError, OrderedFit, fit_ordered, match_nll, poor_elo_verdict
from backtest.beyondelo_report import render
from backtest.elo_check import load_settings
from backtest.elo_data import RATINGS_COLUMNS
from backtest.provenance import report_path, run_info
from fpl import features
from fpl.beyondelo import load_beyondelo
from fpl.ingest import ROOT, load_config

log = logging.getLogger(__name__)

PARTNER_TEXT = {"finished_result": "finished result", "our_rating": "our rating",
                "beyondelo_rating": "beyondELO rating"}
POOLED = "pooled"


@dataclass
class Inputs:
    """Everything the check reads: our ratings, beyondELO's and the fixtures by season, club
    names by season, the Premier League tag, and sha256 hashes of the files read."""

    ours: pd.DataFrame
    beyondelo: dict[str, pd.DataFrame]
    fixtures: dict[str, pd.DataFrame]
    names: dict[str, pd.Series]
    prem: str
    hashes: dict[str, str] = field(default_factory=dict)
    meta_upstream_commit: str = "unset"


def windows(c: dict) -> tuple[Window, list[Window]]:
    """The fit window and the scored windows of the `beyondelo_check` settings."""
    def window(x: dict, name: str | None = None) -> Window:
        first, last = map(int, x["gameweeks"])
        return Window(name or f"{x['season']} GW{first}-{last}", x["season"], first, last)

    return window(c["fit"], "fit"), [window(x) for x in c["scored"]]


def _partner_message(counts: dict[str, dict[str, int]], missing: dict[str, dict],
                     labels: dict[str, str]) -> str:
    lines = ["the outside-source Elo check stopped: a match in a window lacks a partner. "
             "No report was written."]
    for name, c in counts.items():
        lines.append(f"{labels[name]}: {c['matches']} matches; "
                     + ", ".join(f"{c[k]} with a {PARTNER_TEXT[k]}" for k in PARTNERS)
                     + f"; {c['complete']} complete")
        for kind, ids in missing.get(name, {}).items():
            lines.append(f"  no {PARTNER_TEXT[kind]} ({len(ids)}): {', '.join(ids)}")
    return "\n".join(lines)


def _tables(c: dict, inp: Inputs) -> tuple[pd.DataFrame, list[tuple[Window, pd.DataFrame]],
                                           dict[str, dict[str, int]]]:
    """Every window's complete matches and counts; raises `CheckError` on a missing partner."""
    fit_w, scored_w = windows(c)
    counts, missing, labels, out = {}, {}, {}, {}
    for w in [fit_w, *scored_w]:
        t, counts[w.name], gaps = window_table(w, inp.ours, inp.beyondelo[w.season],
                                               inp.fixtures[w.season], inp.prem)
        labels[w.name] = w.name if w.name == w.label else f"{w.name} ({w.label})"
        out[w.name] = t
        if gaps:
            missing[w.name] = gaps
    if missing:
        raise CheckError(_partner_message(counts, missing, labels))
    return out[fit_w.name], [(w, out[w.name]) for w in scored_w], counts


def _fits(c: dict, fit: pd.DataFrame) -> dict[str, OrderedFit]:
    tol, it, halve = float(c["fit_tolerance"]), int(c["max_iterations"]), int(c["max_halvings"])
    y = fit.result.to_numpy()
    out = {}
    for name, gap in (("ours", fit.gap_ours), ("beyondelo", fit.gap_beyondelo),
                      ("baseline", None)):
        try:
            out[name] = fit_ordered(None if gap is None else gap.to_numpy(), y, tol, it, halve)
        except FitError as exc:
            raise FitError(f"the {name} fit on the fit window: {exc}") from exc
    return out


def _log_loss(scored: pd.DataFrame, labels: list[str]) -> pd.DataFrame:
    rows = []
    for label in [*labels, POOLED]:
        x = scored if label == POOLED else scored[scored.window == label]
        rows.append({"window": label, "n": len(x), "ours": x.nll_ours.mean(),
                     "beyondelo": x.nll_beyondelo.mean(), "baseline": x.nll_base.mean()})
    return pd.DataFrame(rows)


def _ranking(scored_w: list[tuple[Window, pd.DataFrame]], inp: Inputs, top_n: int) -> list[dict]:
    out = []
    for w, t in scored_w:
        by_gw = ranking_by_gameweek(t)
        out.append({"window": w.label, "by_gw": by_gw, "median": by_gw.spearman.median(),
                    "min": by_gw.spearman.min(), "last_gw": w.last,
                    "disagreements": rank_disagreements(t, w.last, inp.names[w.season],
                                                        top_n)})
    return out


def _promoted(season: str, be: pd.DataFrame, names: pd.Series) -> list[str]:
    """The names of the clubs beyondELO flags as promoted in `season`, sorted. Raises
    `CheckError` if one has no `dim_team` name."""
    ids = sorted(set(be.team_id[be.promoted]))
    unnamed = [int(t) for t in ids if t not in names.index]
    if unnamed:
        raise CheckError(f"{season}: beyondELO flags clubs {unnamed} as promoted, but they "
                         "have no dim_team name")
    return sorted(names[ids].tolist())


def run_check(s: dict, inp: Inputs) -> dict:
    """The whole check on `inp`; returns everything the report needs.

    Raises `CheckError` when a match in a window lacks a partner, and `FitError` when a fit
    has no finite answer or doesn't converge.
    """
    c = s["beyondelo_check"]
    fit, scored_w, counts = _tables(c, inp)
    fits = _fits(c, fit)
    parts = []
    for w, t in scored_w:
        y = t.result.to_numpy()
        parts.append(t.assign(
            window=w.label, nll_ours=match_nll(fits["ours"], t.gap_ours.to_numpy(), y),
            nll_beyondelo=match_nll(fits["beyondelo"], t.gap_beyondelo.to_numpy(), y),
            nll_base=match_nll(fits["baseline"], None, y)))
    scored = pd.concat(parts, ignore_index=True)
    if len(scored) < 2:
        raise CheckError(f"the scored windows hold {len(scored)} matches; the verdict needs "
                         "at least 2")
    labels = [w.label for w, _ in scored_w]
    verdict = poor_elo_verdict(scored.nll_ours.to_numpy(), scored.nll_beyondelo.to_numpy(),
                               scored.nll_base.to_numpy(), float(c["se_multiple"]),
                               int(c["compare_decimals"]))
    seasons = dict.fromkeys([*fit.season.unique(), *scored.season.unique()])
    promoted = {x: _promoted(x, inp.beyondelo[x], inp.names[x]) for x in seasons}
    return {"settings": s, "counts": counts, "fit_table": fit, "scored": scored, "fits": fits,
            "log_loss": {"all": _log_loss(scored, labels),
                         "without_promoted": _log_loss(scored[~scored.promoted], labels)},
            "verdict": verdict, "promoted": promoted,
            "ranking": _ranking(scored_w, inp, int(c["top_disagreements"]))}


def run(s: dict, inp: Inputs, info: dict, folder: Path) -> Path:
    """Run the check and write its report to `folder`; nothing is written if it stops."""
    results = run_check(s, inp)
    text = render(results, info, inp)
    folder.mkdir(parents=True, exist_ok=True)
    out = report_path(folder, f"{info['date']}-{s['beyondelo_check']['report_suffix']}")
    out.write_text(text, encoding="utf-8")
    return out


def _read_csv(root: Path, rel: str, **kw: object) -> pd.DataFrame:
    """`root / rel` as a frame; raises `CheckError` naming `rel` if the file is missing."""
    try:
        return pd.read_csv(root / rel, **kw)
    except FileNotFoundError as exc:
        raise CheckError(f"{rel} does not exist ({exc.filename})") from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_inputs(s: dict, pcfg: dict, root: Path = ROOT,
                load: Callable[[str, int, str], dict] | None = None,
                load_be: Callable[..., pd.DataFrame] = load_beyondelo) -> Inputs:
    """Read only the seasons the windows name: our ratings from `ratings_file` (other seasons'
    rows dropped on read), beyondELO's through `load_be`, and each season's results and club
    names through `load` (default `fpl.features.load_as_of`) at its last window gameweek in
    `s["mode"]`, so later results can't reach the check. Hashes every file read.

    The loader is looked up at each call, not held by this module, so the Elo check's
    synthetic swap (`tests/elo_check_synth.py`, `stray_callers`) has nothing to miss.
    """
    load = load or features.load_as_of
    c = s["beyondelo_check"]
    fit_w, scored_w = windows(c)
    last: dict[str, int] = {}
    for w in [fit_w, *scored_w]:
        last[w.season] = max(last.get(w.season, w.last), w.last)
    path = root / c["ratings_file"]
    ours = _read_csv(root, c["ratings_file"])
    lacking = [col for col in RATINGS_COLUMNS if col not in ours.columns]
    if lacking:
        raise CheckError(f"{c['ratings_file']} lacks the columns {lacking}")
    hashes = {c["ratings_file"]: _sha256(path)}
    be_dir = pcfg["beyondelo"]["external_dir"]
    beyondelo, fixtures, names = {}, {}, {}
    for season, gw in last.items():
        try:
            beyondelo[season] = load_be(season, base_dir=root / be_dir)
        except FileNotFoundError as exc:
            raise CheckError(f"no beyondELO table for {season}: {exc}") from exc
        hashes[f"{be_dir}/{season}.parquet"] = _sha256(root / be_dir / f"{season}.parquet")
        tables = load(season, gw, s["mode"])
        fixtures[season] = tables["fact_fixture"]
        names[season] = tables["dim_team"].set_index("team_id")["name"]
    # As fpl.publish_decision reads it: an empty commit stays "", not NaN.
    meta = _read_csv(root, c["meta_file"], dtype=str, keep_default_na=False)
    return Inputs(ours=ours[ours.season.isin(last)].reset_index(drop=True), beyondelo=beyondelo,
                  fixtures=fixtures, names=names, prem=pcfg["premier_league_tag"],
                  hashes=hashes, meta_upstream_commit=meta["upstream_commit"].iloc[0])


def main() -> int:
    """Run the check with backtest/config.yaml's windows and write the dated report.

    Reads 2026/27 (a holdout look): run only with Josh's approval logged first.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    s = load_settings()
    pcfg = load_config(ROOT / "config" / "pipeline.yaml")
    try:
        inp = read_inputs(s, pcfg)
        info = run_info(pcfg) | {"date": f"{datetime.now(UTC):%Y-%m-%d}"}
        out = run(s, inp, info, ROOT / s["report_dir"])
    except (CheckError, FitError) as exc:
        log.error("%s", exc)
        return 1
    log.info("report %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
