"""Leakage checks of the xP predictors (brief section 7, "Leakage checklist").

* **Perturbation:** for a sample of as-of gameweeks, every row dated after the as-of snapshot
  is corrupted in a scratch copy of the upstream data: the results (`perturb.corrupt_after`)
  and every other column of every file the loader reads (`perturb_files`). Each predictor is
  re-run; any changed value is a leak, and so is a run that fails only on the corrupted copy.
  The control corrupts everything up to the as-of instead: an honest predictor's output must
  change, which shows it read the copy at all.
* **The planted leak** (`peeking_baselines`) peeks at the target gameweek's points. Every
  case must catch it, or the check itself is broken.
* **Reads round the loader:** every call runs under the read guard, and the model's source
  files pass the static check (`xp_reads`).
* **Refit:** consecutive as-of reads of a model must not give identical forecasts for the
  gameweeks they share, or its fit isn't being refreshed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.elo_data import HarnessError
from backtest.perturb import (
    Corruption,
    Redirect,
    corrupt_after,
    corrupt_up_to,
    restore_season,
)
from backtest.perturb_files import FileRule, corrupt_files_after, corrupt_files_up_to
from backtest.xp_inputs import baselines, read
from backtest.xp_reads import forbid_reads

log = logging.getLogger(__name__)

ModelFn = Callable[[str, int, str], pd.DataFrame]
SORT_KEYS = ["player_id", "team_id", "match_id", "gw"]


def peeking_baselines(season: str, as_of_gw: int, mode: str, **kw: object) -> pd.DataFrame:
    """A deliberately leaky predictor: the baselines with `last5` replaced by the target
    gameweek's actual points. For the positive control and tests only."""
    out = baselines(season, as_of_gw, mode, **kw)
    later = read(season, as_of_gw + 1, mode)["fact_player_gw"]
    points = later[later.gw == as_of_gw + 1].set_index("player_id").points
    return out.assign(last5=out.player_id.map(points).fillna(0.0).astype("float64"))


def changed_cells(a: pd.DataFrame, b: pd.DataFrame) -> int:
    """Cells that differ between two frames, a null equal to a null of any kind (nullable
    dtypes included); a change of shape or columns counts every cell."""
    if list(a.columns) != list(b.columns) or len(a) != len(b):
        return max(len(a), len(b)) * max(len(a.columns), len(b.columns), 1)
    x, y = a.reset_index(drop=True).astype(object), b.reset_index(drop=True).astype(object)
    same = (x == y).fillna(False).astype(bool) | (x.isna() & y.isna())
    return int((~same).to_numpy().sum())


def _sorted(df: pd.DataFrame) -> pd.DataFrame:
    keys = [k for k in SORT_KEYS if k in df.columns]
    return df.sort_values(keys, kind="stable").reset_index(drop=True) if keys else df


def _run(fns: dict[str, ModelFn], names: Sequence[str], season: str, as_of: int,
         mode: str, forbid: Sequence[Path]) -> dict[str, pd.DataFrame | str]:
    """Each named function's sorted output, or its error as text. Each call runs under the
    read guard (`xp_reads.forbid_reads`): a read of `forbid` is an error even if the function
    caught it. A `HarnessError` (the harness itself refusing, as for a holdout season) stops
    the case."""
    out: dict[str, pd.DataFrame | str] = {}
    for name in names:
        with forbid_reads(forbid) as hits:
            try:
                out[name] = _sorted(fns[name](season, as_of, mode))
            except HarnessError:
                raise
            except Exception as exc:  # recorded as a finding, never swallowed silently
                out[name] = f"{type(exc).__name__}: {exc}"
        if hits:
            more = f" (and {len(hits) - 1} more)" if len(hits) > 1 else ""
            out[name] = f"ReadOutsideCopyError: read outside the scratch copy: {hits[0]}{more}"
        if isinstance(out[name], str):
            log.warning("%s(%s, %d) failed: %s", name, season, as_of, out[name])
    return out


def _compare(clean: dict, other: dict) -> dict[str, dict]:
    """Per function: rows, changed cells (None if the clean run failed), any error, and `by`:
    how it changed, "value" (its output differs), "error" (it failed only on the corrupted
    copy, which counts as every cell changed) or None (no change)."""
    res = {}
    for name, b in other.items():
        a = clean[name]
        if isinstance(a, str):
            res[name] = {"rows": 0, "changed": None, "error": f"clean run: {a}", "by": None}
        elif isinstance(b, str):
            res[name] = {"rows": len(a), "changed": max(a.size, 1), "error": b, "by": "error"}
        else:
            n = changed_cells(a, b)
            res[name] = {"rows": len(a), "changed": n, "error": None,
                         "by": "value" if n else None}
    return res


def perturbation_case(fns: dict[str, ModelFn], season: str, as_of: int, src: Path, dst: Path,
                      point: Redirect, rng: np.random.Generator, c: Corruption,
                      rules: dict[str, FileRule], mode: str, files: Sequence[str],
                      controls: Sequence[str] = (), *, forbid: Sequence[Path]) -> dict:
    """One as-of case on the copy `dst` of `src`: clean, after-corrupted and control runs.

    `point(dst)` points every loader read at the copy, and every function call fails on a
    read under `forbid` (the real data: `src` at least). The copy's `files` are restored from
    `src` after each corruption, whatever happens.
    """
    with point(dst):
        clean = _run(fns, list(fns), season, as_of, mode, forbid)
    try:
        cells = {"results": corrupt_after(dst, season, as_of, rng, c),
                 **corrupt_files_after(dst, season, as_of, rng, c, rules)}
        with point(dst):
            dirty = _run(fns, list(fns), season, as_of, mode, forbid)
    finally:
        restore_season(src, dst, season, files)
    try:
        corrupt_up_to(dst, season, as_of, rng, c)
        corrupt_files_up_to(dst, season, as_of, rng, c, rules)
        with point(dst):
            moved = _run(fns, controls, season, as_of, mode, forbid)
    finally:
        restore_season(src, dst, season, files)
    out = {"season": season, "as_of": as_of, "corrupted_cells": cells,
           "functions": _compare(clean, dirty), "control": _compare(clean, moved)}
    log.info("perturbation %s as-of %d: %s; control %s", season, as_of, out["functions"],
             out["control"])
    return out


def refit_findings(outputs: dict[int, pd.DataFrame], column: str) -> tuple[list[str], int]:
    """Consecutive as-of reads whose forecasts for every shared (player, gameweek) are
    identical, and the number of pairs that share any. `outputs` maps as-of to model output."""
    found, pairs = [], 0
    keys = ["player_id", "gw"]
    for a in sorted(outputs):
        if a + 1 not in outputs:
            continue
        x = outputs[a].groupby(keys)[column].sum()
        y = outputs[a + 1].groupby(keys)[column].sum()
        both = x.index.intersection(y.index)
        if len(both) == 0:
            continue
        pairs += 1
        if np.array_equal(x[both].to_numpy(), y[both].to_numpy()):
            found.append(f"as-of {a} to {a + 1}")
    return found, pairs
