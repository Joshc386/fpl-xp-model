"""Match completeness: which finished matches have the data the model needs.

Upstream's own processing flags are not used. They stay false on matches whose results,
xG and player stats are all present (every 2025/26 GW37-38 match), so a match is judged
on its data instead.
"""

from __future__ import annotations

import pandas as pd

from fpl.frames import checked_merge


def complete_matches(
    matches: pd.DataFrame, pms: pd.DataFrame, players: pd.DataFrame, teams: pd.DataFrame
) -> pd.Series:
    """True for each complete match, indexed like `matches`.

    A complete match is finished, has both team xG values, and has player rows for each
    of its clubs that is in `teams` (the Premier League). A player's club is his
    `team_code` in the snapshot named by the row's `snapshot_gw` (for a cup or European
    match, the gameweek it was played in). Opponents outside the
    Premier League have no player rows and are not required to.
    """
    rows = checked_merge(
        pms[["snapshot_gw", "player_id", "match_id"]],
        players[["snapshot_gw", "player_id", "team_code"]],
        on=["snapshot_gw", "player_id"], how="left", validate="many_to_one",
        name="complete: playermatchstats -> players",
    )
    have = (
        rows.dropna(subset=["team_code"])[["match_id", "team_code"]]
        .drop_duplicates()
        .assign(_has_rows=True)
    )
    sides = pd.concat([
        matches[["match_id", side]].set_axis(["match_id", "team_code"], axis=1)
        for side in ("home_team", "away_team")
    ])
    need = sides[sides.team_code.isin(teams["code"])].drop_duplicates()
    need = checked_merge(
        need, have, on=["match_id", "team_code"], how="left", validate="many_to_one",
        name="complete: club rows",
    )
    lacking = set(need.match_id[need["_has_rows"].isna()])
    has_xg = matches.home_expected_goals_xg.notna() & matches.away_expected_goals_xg.notna()
    finished = matches.finished.fillna(False).astype(bool)
    return (finished & has_xg & ~matches.match_id.isin(lacking)).astype(bool)
