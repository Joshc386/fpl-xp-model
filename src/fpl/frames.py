"""Small checked helpers shared by the cleaning functions: joins, types, team codes."""

from __future__ import annotations

import numpy as np
import pandas as pd


class CleanError(RuntimeError):
    """The data cannot be cleaned under the documented rules."""


class JoinError(CleanError):
    """A join lost rows, duplicated rows, or found no match where one is required."""


def checked_merge(
    left: pd.DataFrame, right: pd.DataFrame, *, how: str, validate: str, name: str, **keys: object
) -> pd.DataFrame:
    """Merge, then assert the row count is unchanged; raise `JoinError` otherwise."""
    try:
        out = left.merge(right, how=how, validate=validate, **keys)
    except pd.errors.MergeError as exc:
        raise JoinError(f"{name}: {exc}") from exc
    if len(out) != len(left):
        raise JoinError(f"{name}: rows changed from {len(left)} to {len(out)}")
    return out


def to_int(series: pd.Series, name: str, nullable: bool = False) -> pd.Series:
    """Whole-number column as int64 (or Int64); raise on nulls or fractions."""
    vals = pd.to_numeric(series)
    if not nullable and vals.isna().any():
        raise CleanError(f"{name}: {int(vals.isna().sum())} null values")
    if (vals.dropna() % 1 != 0).any():
        raise CleanError(f"{name}: non-integer values")
    return vals.round().astype("Int64" if nullable else "int64")


def tenths(now_cost: pd.Series, name: str) -> pd.Series:
    """GBP m (15.8) to integer tenths (158)."""
    return to_int(pd.Series(np.rint(now_cost.to_numpy() * 10), index=now_cost.index), name)


def normalise_kickoff(kickoff: pd.Series) -> pd.Series:
    """ISO 8601 UTC with a trailing Z; naive input is UTC, offsets are converted."""
    parsed = pd.to_datetime(kickoff, utc=True, format="ISO8601")
    return parsed.dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def map_codes(codes: pd.Series, teams: pd.DataFrame, name: str) -> pd.Series:
    """Team code -> teams.id (float, NaN where there is no such team)."""
    left = pd.DataFrame({"code": codes.to_numpy(dtype="float64")})
    out = checked_merge(
        left, teams[["code", "id"]], on="code", how="left", validate="many_to_one", name=name
    )
    return out["id"].set_axis(codes.index)
