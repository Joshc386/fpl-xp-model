"""Which matches an as-of read holds (pure; no file access, no master files).

A read at as-of gameweek g holds every match whose `gw` is up to g, in any competition.
A Premier League fixture's `gw` is upstream's gameweek (its folder); those after g stay as
schedule only, with results blanked. A cup or European match's `gw` is the gameweek it was
played in: the latest gameweek whose deadline is at or before kickoff, or 0 before the GW1
deadline. Upstream files such a match in a later folder, so the folder says nothing about
when it was played. Cup and European matches with a later `gw` are left out entirely: in a
knockout cup a future tie reveals who won the earlier rounds.

Deadlines are derived from the schedule (a gameweek's first Premier League kickoff minus
the configured offset), so backtests never need the master `gameweek_summaries.csv`.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from fpl.schema import RESULT_COLUMNS

log = logging.getLogger(__name__)


def kickoffs(matches: pd.DataFrame) -> pd.Series:
    """Kickoff times as UTC timestamps (naive input is UTC); NaT where there is none."""
    return pd.to_datetime(matches["kickoff_time"], utc=True, format="ISO8601")


def _naive(times: pd.Series) -> np.ndarray:
    """UTC times as plain datetime64 (NaT stays NaT, and compares false)."""
    return times.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")


def _first_last(
    matches: pd.DataFrame, n_gw: int, prem_tag: str
) -> tuple[pd.Series, pd.Series]:
    """Each gameweek's first and last Premier League kickoff (NaT where it has none)."""
    prem = matches[matches.tournament == prem_tag]
    by_gw = kickoffs(prem).groupby(prem.snapshot_gw)
    gws = range(1, n_gw + 1)
    return by_gw.min().reindex(gws), by_gw.max().reindex(gws)


def deadlines(
    matches: pd.DataFrame, n_gw: int, prem_tag: str, offset_minutes: int
) -> pd.Series:
    """Each gameweek's deadline: its first Premier League kickoff minus the offset.

    `matches` carries `snapshot_gw`, `tournament` and `kickoff_time` for every folder. A
    gameweek with no Premier League fixture (wholly postponed, or its file missing) takes the
    last Premier League kickoff of the latest earlier gameweek that has one, which can only
    date a cup tie late, never early (NaT for GW1). A missing file is reported by validation,
    and nothing is returned from a failed run. A warning names such gameweeks.
    """
    first, last = _first_last(matches, n_gw, prem_tag)
    empty = first.isna()
    if empty.any():
        log.warning("gameweeks %s have no Premier League fixture; each takes the previous "
                    "gameweek's last kickoff as its deadline", empty[empty].index.tolist())
    return (first - pd.Timedelta(minutes=offset_minutes)).where(~empty, last.ffill().shift(1))


def deadline_problems(
    matches: pd.DataFrame, n_gw: int, prem_tag: str, offset_minutes: int
) -> list[str]:
    """Problems with the derived deadlines: they must strictly increase with the gameweek.

    Gameweeks with no Premier League fixture (which take the fallback) are skipped.
    """
    first, _ = _first_last(matches, n_gw, prem_tag)
    due = (first - pd.Timedelta(minutes=offset_minutes)).dropna()
    bad = due.index[1:][(due.diff().iloc[1:] <= pd.Timedelta(0)).to_numpy()]
    return [f"derived deadline of GW{g} is not after that of the gameweek before it "
            "(a mis-dated Premier League kickoff?)" for g in bad]


def played_gw(kick: pd.Series, deadline: pd.Series) -> pd.Series:
    """The latest gameweek whose deadline is at or before `kick`; 0 before the GW1 deadline.

    NaN where there is no kickoff time.
    """
    due = _naive(deadline)[None, :] <= _naive(kick)[:, None]
    gw = np.where(due, deadline.index.to_numpy()[None, :], 0).max(axis=1).astype("float64")
    return pd.Series(gw, index=kick.index).where(kick.notna())


def select_matches(
    matches: pd.DataFrame, as_of_gw: int, n_gw: int, prem_tag: str, offset_minutes: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split `matches` (all folders, unblanked) into (held, left out).

    Held: every Premier League match, blanked to schedule only in folders after
    `as_of_gw`, and every other match played in a gameweek up to `as_of_gw`; its
    `gameweek` becomes the gameweek it was played in (`snapshot_gw` stays its folder).
    Left out: the rest, including cup and European matches with no kickoff time. At the
    last gameweek every match counts, and one with no kickoff time keeps its folder's.
    """
    is_prem = matches.tournament == prem_tag
    cup_gw = played_gw(kickoffs(matches), deadlines(matches, n_gw, prem_tag, offset_minutes))
    held = is_prem | (cup_gw <= as_of_gw)
    if as_of_gw >= n_gw:
        held = pd.Series(True, index=matches.index)
    out = matches[held].copy()
    cups = ~out.tournament.eq(prem_tag) & cup_gw[held].notna()
    out.loc[cups, "gameweek"] = cup_gw[held][cups]
    later = out.tournament.eq(prem_tag) & (out.snapshot_gw > as_of_gw)
    out.loc[later, RESULT_COLUMNS] = np.nan
    out.loc[later, "finished"] = False
    return out.reset_index(drop=True), matches[~held].reset_index(drop=True)
