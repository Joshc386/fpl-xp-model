"""The deadline clock: which gameweek is next, and which is the as-of gameweek.

Pure functions over a deadlines table, so they are testable without files. Live mode only:
the deadlines come from the master `gameweek_summaries.csv`, which backtests never read.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd


class DeadlineError(ValueError):
    """The deadlines are malformed, or the season has no next gameweek."""


def parse_deadlines(summaries: pd.DataFrame, n_gw: int | None = None) -> pd.Series:
    """Deadlines by gameweek (UTC timestamps), from `id` and `deadline_time` columns.

    Offset, `Z` and naive stamps are all read as UTC. Raises `DeadlineError` unless the
    gameweeks are 1..N (N equal to `n_gw`, if given), each with a deadline, and the
    deadlines strictly increase with the gameweek.
    """
    if summaries.empty or summaries["deadline_time"].isna().any():
        raise DeadlineError("deadlines: the table is empty or has a gameweek without a deadline")
    try:
        when = pd.to_datetime(summaries["deadline_time"], utc=True, format="ISO8601")
    except (ValueError, TypeError) as exc:
        raise DeadlineError(f"deadlines: cannot parse deadline_time ({exc})") from exc
    out = pd.Series(when.array, index=summaries["id"].astype("int64").to_numpy()).sort_index()
    if out.index.tolist() != list(range(1, len(out) + 1)):
        raise DeadlineError(f"deadlines: gameweeks are not 1..N: {out.index.tolist()}")
    if n_gw is not None and len(out) != n_gw:
        raise DeadlineError(f"deadlines: {len(out)} gameweeks, expected {n_gw}")
    if not out.is_monotonic_increasing or out.duplicated().any():
        raise DeadlineError("deadlines: not strictly increasing with the gameweek")
    return out


def next_gameweek(deadlines: pd.Series, run_utc: datetime) -> int:
    """The first gameweek whose deadline is strictly after `run_utc`.

    A run at the exact deadline treats it as passed. A naive `run_utc` is taken as UTC.
    Raises `DeadlineError` once the last deadline has passed.
    """
    run = pd.Timestamp(run_utc)
    run = run.tz_localize("UTC") if run.tzinfo is None else run.tz_convert("UTC")
    upcoming = deadlines[deadlines > run]
    if upcoming.empty:
        last = int(deadlines.index[-1])
        raise DeadlineError(f"{run:%Y-%m-%dT%H:%M:%SZ} is at or after the GW{last} deadline")
    return int(upcoming.index[0])


def as_of_gameweek(deadlines: pd.Series, run_utc: datetime) -> int:
    """The gameweek before the next one; 0 before the GW1 deadline."""
    return next_gameweek(deadlines, run_utc) - 1
