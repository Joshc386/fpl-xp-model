"""fact_shot: one row per shot of a Premier League complete match.

Pure over DataFrames. A shot's club comes from `is_home` through the match's clubs, its
shooter is FPL's `player_id` (null when upstream is blank, or on an own goal), and its
`clock` places it on the same scale as the on-pitch spells (`fpl.spells`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from fpl.frames import checked_merge, to_int
from fpl.schema import column_names
from fpl.validate import ValidationError

# Clock position of first-half stoppage time: after label 45, before the second half's 46.
FIRST_HALF_STOPPAGE = 45.5


def shot_clock(minute: pd.Series, added_time: pd.Series) -> pd.Series:
    """The match clock of a shot or incident.

    `minute` 90 with added time is 90 + added time, and `minute` 45 with added time is
    first-half stoppage (`FIRST_HALF_STOPPAGE`); every other minute is itself.
    """
    minute = minute.astype("float64")
    added = added_time.astype("float64")
    out = np.where((minute == 90) & added.notna(), minute + added, minute)
    out = np.where((minute == 45) & added.notna(), FIRST_HALF_STOPPAGE, out)
    return pd.Series(out, index=minute.index, dtype="float64")


def _complete_premier_league_shots(
    shots: pd.DataFrame, fixture: pd.DataFrame, prem_tag: str
) -> tuple[pd.DataFrame, dict[str, int]]:
    """The shots of Premier League complete matches, with their clubs, and the rows dropped.

    A shot of a match missing from `fixture` (no kickoff time), of another competition, or of a
    match that is not complete is dropped and counted. A blank `is_home` on a kept shot is a
    `ValidationError`, since the shot then has no club.
    """
    flags = fixture[
        ["match_id", "tournament", "stats_complete", "home_team_id", "away_team_id"]
    ].assign(_known=True)
    df = checked_merge(shots, flags, on="match_id", how="left", validate="many_to_one",
                       name="shots -> fact_fixture")
    unknown = df["_known"].isna()
    other = ~unknown & (df.tournament != prem_tag)
    open_ = ~unknown & ~other & ~df.stats_complete.fillna(False).astype(bool)
    dropped = {
        "match_has_no_kickoff_time": int(unknown.sum()),
        "match_not_premier_league": int(other.sum()),
        "match_not_complete": int(open_.sum()),
    }
    df = df[~unknown & ~other & ~open_].reset_index(drop=True)
    if df.is_home.isna().any():
        raise ValidationError([f"fact_shot: {int(df.is_home.isna().sum())} shots of Premier League "
                               "complete matches have a blank is_home, so no club"])
    return df, dropped


def build_fact_shot(
    shots: pd.DataFrame, fixture: pd.DataFrame, pmatch: pd.DataFrame, prem_tag: str
) -> tuple[pd.DataFrame, dict[str, int], dict[str, int]]:
    """fact_shot, the rows dropped by reason, and the kept rows counted by reason.

    `shots` is the raw shots.csv rows, `fixture` the fact_fixture rows and `pmatch` the
    fact_player_match rows. Only the shots of Premier League complete matches are built (the
    others are dropped and counted, see `_complete_premier_league_shots`). A shot's club is the
    home or away team by `is_home`. Kept but counted: `player_blank` (upstream gave no shooter),
    `own_goal` (the shooter's club is not the shot's, so the shooter is nulled) and
    `shooter_not_in_player_match` (a shooter with no fact_player_match row in the match).
    """
    df, dropped = _complete_premier_league_shots(shots, fixture, prem_tag)
    club = pmatch[["player_id", "match_id", "team_id"]].astype({"player_id": "float64"})
    club = club.rename(columns={"team_id": "shooter_team"}).assign(_in_match=True)
    df = checked_merge(df, club, on=["player_id", "match_id"], how="left",
                       validate="many_to_one", name="shots -> fact_player_match")
    team = df.home_team_id.where(df.is_home.astype(bool), df.away_team_id)
    own = df.shooter_team.notna() & (df.shooter_team != team)
    counted = {
        "player_blank": int(df.player_id.isna().sum()),
        "own_goal": int(own.sum()),
        "shooter_not_in_player_match": int((df.player_id.notna() & df["_in_match"].isna()).sum()),
    }
    out = pd.DataFrame({
        "match_id": df.match_id, "shot_index": to_int(df.shot_index, "shot_index"),
        "team_id": to_int(team, "team_id"),
        "player_id": to_int(df.player_id.where(~own), "player_id", nullable=True),
        "minute": to_int(df.minute, "minute"),
        "added_time": to_int(df.added_time, "added_time", nullable=True),
        "clock": shot_clock(df.minute, df.added_time), "situation": df.situation,
        "outcome": df.outcome, "xg": df.xg.astype("float64"),
        "is_penalty": (df.situation == "penalty").to_numpy(), "is_own_goal": own.to_numpy(),
    })
    return out[column_names("fact_shot")], dropped, counted
