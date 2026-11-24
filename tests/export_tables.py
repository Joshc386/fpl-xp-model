"""Small hand-built processed tables for the export tests.

Two clubs (ids 1 and 2) and a season at as-of gameweek 3. The clubs play a double gameweek 2.
Gameweek 3's Premier League match (m4) is finished but not complete, and a finished, complete
cup match (m5) sits in the same gameweek. The hand-computed answers are in
`test_export_players.py`.
"""

from __future__ import annotations

import pandas as pd

from fpl.schema import PROCESSED_SCHEMA, column_names, expected_dtype

SEASON = "2026-2027"
PREM = "prem"
CUP = "efl-cup"
AS_OF = 3


def frame(table: str, rows: list[dict]) -> pd.DataFrame:
    """Rows as a processed table: contract columns, order and dtypes (missing keys are null)."""
    cols = column_names(table)
    df = pd.DataFrame(rows, columns=cols)
    spec = {c: (k, n) for c, k, n in PROCESSED_SCHEMA[table]}
    return df.astype({c: expected_dtype(*spec[c]) for c in cols})


def fixture(match_id: str, gw: int, home: int, away: int, *, tournament: str = PREM,
            finished: bool = True, complete: bool = True) -> dict:
    """A fact_fixture row; the score is 1-0 when finished."""
    return {
        "match_id": match_id, "season": SEASON, "gw": gw,
        "kickoff_utc": f"2026-09-{gw:02d}T14:00:00Z",
        "tournament": tournament, "home_team_id": home, "away_team_id": away,
        "finished": finished, "stats_complete": finished and complete,
        "home_goals": 1 if finished else None, "away_goals": 0 if finished else None,
    }


def gw_row(player: int, team: int | None, gw: int, *, points: int = 0, minutes: int = 0,
           starts: int = 0, dc: int = 0, price: int = 50, tin: int = 0, tout: int = 0) -> dict:
    """A fact_player_gw row."""
    return {
        "player_id": player, "team_id": team, "season": SEASON, "gw": gw, "points": points,
        "minutes": minutes, "starts": starts, "bonus": 0, "bps": 0, "fpl_goals": 0,
        "fpl_assists": 0, "yellow": 0, "red": 0,
        "own_goals": 0, "goals_conceded": 0, "tackles": 0, "cbi": 0, "recoveries": 0,
        "defensive_contribution": dc, "price_tenths": price, "selected_pct": 1.0,
        "transfers_in": tin, "transfers_out": tout,
    }


def pm_row(player: int, team: int, match: str, minutes: int, xg: float = 0.0,
           xa: float = 0.0) -> dict:
    """A fact_player_match row with zero counts."""
    zero = dict.fromkeys(["goals", "assists", "pens_scored", "pens_missed", "tackles",
                          "interceptions", "clearances", "blocks", "recoveries", "saves"], 0)
    return {"player_id": player, "team_id": team, "match_id": match, "minutes": minutes,
            "xg": xg, "xa": xa} | zero


def player(pid: int, team: int, pos: str, price: int, *, pen: int | None = None,
           status: str = "a", news: str | None = None, chance: int | None = None,
           start: int = 0, week: int = 0, tin: int = 0, tout: int = 0) -> dict:
    """A dim_player row; `start` and `week` are the price changes in tenths."""
    return {
        "player_id": pid, "player_code": 1000 + pid, "web_name": f"P{pid}", "team_id": team,
        "position": pos, "price_tenths": price, "status": status, "chance_next": chance,
        "news": news, "selected_pct": 12.5, "pen_order": pen, "fk_order": None,
        "corner_order": None, "ep_next": 3.0,
        "price_change_start_tenths": start, "price_change_gw_tenths": week,
        "transfers_in_gw": tin, "transfers_out_gw": tout,
    }


def tables() -> dict[str, pd.DataFrame]:
    """The hand-built tables.

    Players: A (10) plays; B (20) never plays; C (30) has no gameweek 3 row (his club's
    fixture was unfinished, so the row is held); D (40) is new in gameweek 3.
    """
    fx = [
        fixture("m1", 1, 1, 2), fixture("m2", 2, 2, 1), fixture("m3", 2, 1, 2),
        fixture("m4", 3, 1, 2, complete=False), fixture("m5", 3, 1, 2, tournament=CUP),
        fixture("m6", 4, 1, 2, finished=False),
    ]
    teams = pd.DataFrame({
        "team_id": [1, 2], "team_code": [11, 12], "name": ["Alpha", "Beta"],
        "short_name": ["ALP", "BET"], "upstream_elo": [None, None],
    }).astype({"upstream_elo": "float64"})
    gw = [
        gw_row(10, 1, 1, points=6, minutes=90, starts=1, dc=4, price=55, tin=10, tout=4),
        gw_row(10, 1, 2, points=10, minutes=135, starts=2, dc=6, price=55, tin=20, tout=5),
        gw_row(10, 1, 3, points=2, minutes=90, starts=1, dc=2, price=56, tin=300, tout=100),
        gw_row(10, 1, 4, points=99, minutes=90, starts=1, dc=99, price=99),  # after as-of
        gw_row(20, 2, 1, price=40), gw_row(20, 2, 2, price=40), gw_row(20, 2, 3, price=40),
        gw_row(30, 2, 1, points=3, minutes=60, starts=1, dc=1, price=45),
        gw_row(30, 2, 2, points=0, minutes=0, price=45),
        gw_row(40, 1, 3, points=1, minutes=10, starts=0, price=60, tin=7, tout=9),
    ]
    pm = [
        pm_row(10, 1, "m1", 90, 0.5, 0.1), pm_row(10, 1, "m2", 90, 0.3, 0.0),
        pm_row(10, 1, "m3", 45, 0.2, 0.4), pm_row(10, 1, "m5", 90, 5.0, 5.0),   # cup
        pm_row(10, 1, "m4", 90, 9.0, 9.0),                                         # incomplete
        pm_row(20, 2, "m1", 0), pm_row(30, 2, "m1", 60, 0.1, 0.2),
    ]
    dp = [
        player(10, 1, "MID", 56, pen=1, news="Knock", chance=75, status="d", start=12, week=1,
               tin=300, tout=100),
        player(20, 2, "GKP", 40),
        player(30, 2, "DEF", 45, pen=3, start=-2, week=-1, tin=5, tout=8),
        player(40, 1, "FWD", 60, pen=2, tin=7, tout=9),
    ]
    return {
        "dim_player": frame("dim_player", dp), "dim_team": teams,
        "fact_fixture": frame("fact_fixture", fx),
        "fact_player_match": frame("fact_player_match", pm),
        "fact_player_gw": frame("fact_player_gw", gw),
    }
