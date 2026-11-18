"""Small hand-built frames for the outside-source Elo check's tests. All invented."""

from __future__ import annotations

import pandas as pd

PREM = "prem"


def fixtures(rows: list[tuple], season: str = "2025-2026") -> pd.DataFrame:
    """`fact_fixture` rows (match_id, gw, home_id, away_id, home_goals, away_goals, finished)."""
    df = pd.DataFrame(rows, columns=["match_id", "gw", "home_team_id", "away_team_id",
                                     "home_goals", "away_goals", "finished"])
    df["season"], df["tournament"] = season, PREM
    df["kickoff_utc"] = [f"2025-09-{10 + int(g):02d}T15:00:00Z" for g in df.gw]
    for c in ("home_team_id", "away_team_id", "home_goals", "away_goals"):
        df[c] = df[c].astype("Int64")
    return df


def ratings(fx: pd.DataFrame, values: dict[int, float], col: str = "elo_before",
            drop: tuple[tuple[str, int], ...] = ()) -> pd.DataFrame:
    """One row per club per fixture with `values[team_id]` as the before-match rating, in the
    shape of `elo_ratings.csv` (col `elo_before`) or `ext_beyondelo` (`beyondelo_before`)."""
    rows = []
    for r in fx.itertuples():
        for t, home in ((int(r.home_team_id), True), (int(r.away_team_id), False)):
            if (r.match_id, t) in drop:
                continue
            rows.append({"team_id": t, "match_id": r.match_id, "season": r.season,
                         "gw": int(r.gw), "kickoff_utc": r.kickoff_utc, "home": home,
                         col: values[t]})
    return pd.DataFrame(rows)


def beyondelo(fx: pd.DataFrame, values: dict[int, float], promoted: set[int] = frozenset(),
              drop: tuple[tuple[str, int], ...] = ()) -> pd.DataFrame:
    """`ext_beyondelo` rows with the `promoted` flag set for the clubs in `promoted`."""
    df = ratings(fx, values, "beyondelo_before", drop)
    return df.assign(promoted=df.team_id.isin(promoted))
