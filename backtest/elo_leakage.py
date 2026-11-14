"""Leakage checks of the Elo component: perturbation after an as-of gameweek and within one.

Each case runs the public functions on a clean scratch copy, corrupts the copy, runs them
again and compares. The copy is restored afterwards, whatever happens.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.perturb import (
    Corruption,
    Redirect,
    corrupt_after,
    corrupt_up_to,
    corrupt_within,
    restore_season,
)
from fpl.features import load_as_of
from fpl.models.team_goals import elo_goals

log = logging.getLogger(__name__)

ModelFn = Callable[[str, int, str], pd.DataFrame]
KEYS = ["season", "match_id", "team_id"]


def changed_values(a: pd.DataFrame, b: pd.DataFrame) -> int:
    """Cells that differ between two frames (NaN equals NaN); a shape change counts all."""
    if list(a.columns) != list(b.columns) or len(a) != len(b):
        return max(len(a), len(b)) * max(len(a.columns), len(b.columns), 1)
    a, b = a.reset_index(drop=True), b.reset_index(drop=True)
    same = (a == b) | (a.isna() & b.isna())
    return int((~same).to_numpy().sum())


def peeking_goals(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
    """A deliberately leaky Elo goals model: it nudges every rate by the next gameweek's goals.

    For tests and the positive control only. The perturbation check must flag it.
    """
    out = elo_goals(season, as_of_gw, mode)
    fx = load_as_of(season, as_of_gw + 1, mode)["fact_fixture"]
    nxt = fx[(fx.gw == as_of_gw + 1) & fx.finished]
    peek = float((3 * nxt.home_goals + nxt.away_goals).sum())
    return out.assign(lambda_for=out.lambda_for * (1.0 + 1e-3 * peek))


def _corrupted_run(fns: dict[str, ModelFn], names: Sequence[str], corrupt: Callable[[], int],
                   season: str, as_of: int, ctx: tuple[Path, Path, Redirect, str]
                   ) -> tuple[int, dict]:
    """Corrupt the copy, run the named functions on it, and always restore it."""
    src, dst, point, mode = ctx
    try:
        cells = corrupt()
        with point(dst):
            out = {name: fns[name](season, as_of, mode) for name in names}
    finally:
        restore_season(src, dst, season)
    return cells, out


def after_as_of_case(fns: dict[str, ModelFn], season: str, as_of: int, src: Path, dst: Path,
                     point: Redirect, rng: np.random.Generator, c: Corruption, mode: str,
                     controls: Sequence[str] = ()) -> dict:
    """Corrupt every result after `as_of` and count changed output values per function.

    The functions in `controls` are also run with every result up to `as_of` corrupted
    instead: their output must change, which shows they read the copy at all. `point(dst)`
    points the loader at the copy (`perturb.redirect` in the real run).
    """
    ctx = (src, dst, point, mode)
    with point(dst):
        clean = {name: fn(season, as_of, mode) for name, fn in fns.items()}
    cells, dirty = _corrupted_run(fns, list(fns), lambda: corrupt_after(dst, season, as_of, rng, c),
                                  season, as_of, ctx)
    _, moved = _corrupted_run(fns, controls, lambda: corrupt_up_to(dst, season, as_of, rng, c),
                              season, as_of, ctx)

    def diff(other: dict) -> dict:
        return {n: {"rows": len(clean[n]), "changed": changed_values(clean[n], other[n])}
                for n in other}

    out = {"season": season, "as_of": as_of, "corrupted_cells": cells, "functions": diff(dirty),
           "control": diff(moved)}
    log.info("perturbation %s as-of %d: %s; control %s", season, as_of, out["functions"],
             out["control"])
    return out


def _middle_kickoff(ratings: pd.DataFrame, season: str, gw: int) -> str:
    kicks = sorted(ratings.loc[(ratings.season == season) & (ratings.gw == gw), "kickoff_utc"]
                   .unique())
    if not kicks:
        raise ValueError(f"{season} GW{gw} has no rated kickoff")
    return str(kicks[len(kicks) // 2])


def _compare_within(clean: pd.DataFrame, dirty: pd.DataFrame, split: pd.Timestamp,
                    season: str, gw: int) -> dict[str, int]:
    """Count the changes the within-gameweek test forbids, and the control's changes.

    Forbidden: `elo_before` at any kickoff up to `split`, or `elo_after` before it. Control:
    GW `gw` rows of `season` from the split on whose `elo_after` changed. A row missing from
    the corrupted run counts as changed.
    """
    m = clean.merge(dirty, on=KEYS, how="left", suffixes=("", "_dirty"))
    kick = pd.to_datetime(m.kickoff_utc, utc=True)
    up_to, before = kick <= split, kick < split
    before_changed = (m.elo_before != m.elo_before_dirty) | m.elo_before_dirty.isna()
    after_changed = (m.elo_after != m.elo_after_dirty) | m.elo_after_dirty.isna()
    target = (m.season == season) & (m.gw == gw) & ~before
    return {"checked": int(up_to.sum()),
            "changed": int((up_to & before_changed).sum() + (before & after_changed).sum()),
            "control_rows": int(target.sum()),
            "control_changed": int((target & after_changed).sum())}


def within_gameweek_case(fn: ModelFn, season: str, gw: int, src: Path, dst: Path,
                         point: Redirect, rng: np.random.Generator, c: Corruption,
                         mode: str) -> dict:
    """At as-of `gw`, corrupt GW `gw` results from its middle kickoff on, and everything later.

    `elo_before` at every kickoff up to the split, and `elo_after` before it, must not
    change. The control counts GW `gw` rows from the split on whose `elo_after` did change,
    which shows the corruption reached the ratings.
    """
    with point(dst):
        clean = fn(season, gw, mode)
    split_text = _middle_kickoff(clean, season, gw)
    split = pd.Timestamp(split_text)
    try:
        cells = corrupt_after(dst, season, gw, rng, c)
        cells += corrupt_within(dst, season, gw, split, rng, c)
        with point(dst):
            dirty = fn(season, gw, mode)
    finally:
        restore_season(src, dst, season)
    out = {"season": season, "gw": gw, "split": split_text, "corrupted_cells": cells,
           **_compare_within(clean, dirty, split, season, gw)}
    log.info("within-gameweek %s GW%d: %s", season, gw, out)
    return out
