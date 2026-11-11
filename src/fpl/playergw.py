"""fact_player_gw: FPL's own per-gameweek figures, gated on the club's fixtures being finished."""

from __future__ import annotations

import pandas as pd

from fpl.frames import CleanError, checked_merge, map_codes, tenths, to_int
from fpl.schema import PROCESSED_SCHEMA


def _club_of(pgs: pd.DataFrame, players: pd.DataFrame) -> pd.Series:
    """Each row's club (`team_code`) in the snapshot of its gameweek folder; NaN if absent."""
    keyed = checked_merge(
        pgs[["snapshot_gw", "id"]],
        players[["snapshot_gw", "player_id", "team_code"]],
        left_on=["snapshot_gw", "id"], right_on=["snapshot_gw", "player_id"],
        how="left", validate="many_to_one", name="player_gameweek_stats -> players",
    )
    return keyed["team_code"].set_axis(pgs.index)


def _gameweek_holds(
    pgs: pd.DataFrame, club: pd.Series, matches: pd.DataFrame, prem_tag: str
) -> tuple[pd.Series, pd.Series]:
    """Which pgs rows to hold back: (club has an unfinished fixture, player has no club).

    A club with no Premier League fixture that gameweek (a blank gameweek) has nothing
    unfinished. A player with no club in the snapshot is held while *any* Premier League
    fixture in that gameweek is unfinished.
    """
    prem = matches[matches.tournament == prem_tag]
    fin = prem.finished.fillna(False).astype(bool)
    sides = [
        pd.DataFrame({"gw": prem.gameweek, "team_code": prem[side], "open": ~fin})
        for side in ("home_team", "away_team")
    ]
    clubs = pd.concat(sides).groupby(["gw", "team_code"], as_index=False)["open"].any()
    keyed = pd.DataFrame({"gw": pgs["gw"].to_numpy(), "team_code": club.to_numpy()})
    flagged = checked_merge(
        keyed.astype("float64"), clubs.astype({"open": "bool"}),
        on=["gw", "team_code"], how="left", validate="many_to_one",
        name="player_gameweek_stats -> club fixtures",
    )
    club_hold = flagged["open"].eq(True).set_axis(pgs.index)
    open_gws = set(clubs.loc[clubs["open"], "gw"])
    return club_hold, club.isna() & pgs["gw"].isin(open_gws)


def build_fact_player_gw(
    pgs: pd.DataFrame, players: pd.DataFrame, matches: pd.DataFrame, teams: pd.DataFrame,
    season: str, prem_tag: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """fact_player_gw from FPL's own per-gameweek stats; minutes are FPL's, not minutes_played.

    A row is kept only once every Premier League fixture the player's club has in that
    gameweek is finished (`finished`, not complete); the others are dropped and counted.
    A player with no club in the snapshot waits for every Premier League fixture of the gameweek.
    `team_id` is the club from that gameweek's snapshot, mapped through `teams.code`; null for a
    player missing from the snapshot.
    """
    club = _club_of(pgs, players)
    club_hold, no_club_hold = _gameweek_holds(pgs, club, matches, prem_tag)
    dropped = {
        "club_fixture_not_finished": int(club_hold.sum()),
        "no_club_gameweek_not_finished": int(no_club_hold.sum()),
    }
    keep = ~(club_hold | no_club_hold)
    pgs, club = pgs[keep], club[keep]
    team = map_codes(club, teams, "fact_player_gw team")
    if (team.isna() & club.notna()).any():
        raise CleanError("fact_player_gw: a player's team_code is not in teams")
    cols = {
        "points": "event_points", "minutes": "minutes", "starts": "starts", "bonus": "bonus",
        "bps": "bps", "yellow": "yellow_cards", "red": "red_cards", "own_goals": "own_goals",
        "goals_conceded": "goals_conceded", "tackles": "tackles",
        "cbi": "clearances_blocks_interceptions", "recoveries": "recoveries",
        "defensive_contribution": "defensive_contribution",
        "transfers_in": "transfers_in_event", "transfers_out": "transfers_out_event",
    }
    out = pd.DataFrame({
        "player_id": to_int(pgs["id"], "player_id"),
        "team_id": to_int(team, "team_id", nullable=True), "season": season,
        "gw": to_int(pgs["gw"], "gw"),
    })
    for col, src in cols.items():
        out[col] = to_int(pgs[src], col)
    out["price_tenths"] = tenths(pgs.now_cost, "now_cost")
    out["selected_pct"] = pgs.selected_by_percent
    cols_out = [c for c, _, _ in PROCESSED_SCHEMA["fact_player_gw"]]
    return out[cols_out].reset_index(drop=True), dropped
