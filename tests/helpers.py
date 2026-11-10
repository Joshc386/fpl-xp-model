"""Small builders for synthetic raw frames used by the unit tests."""

from __future__ import annotations

import pandas as pd

from fpl.schema import RAW_SCHEMA


def blank_frame(file: str, rows: list[dict]) -> pd.DataFrame:
    """Build a raw-file frame with every required column, then apply the rows.

    Columns absent from a row stay null; string/bool/number dtypes follow the
    schema, as `ingest` would read them.
    """
    spec = RAW_SCHEMA[file]
    cols = spec["str"] + spec["bool"] + spec["num"]
    df = pd.DataFrame(rows, columns=cols)
    for c in spec["bool"]:
        df[c] = df[c].astype("boolean")
    for c in spec["num"]:
        df[c] = df[c].astype("float64")
    return df


def teams_frame(pairs: list[tuple[int, int]]) -> pd.DataFrame:
    """Teams from (id, code) pairs."""
    rows = [
        {"id": i, "code": c, "name": f"Team{i}", "short_name": f"T{i:02d}", "elo": 1500.0 + i}
        for i, c in pairs
    ]
    return blank_frame("teams", rows)


def match_row(match_id: str, home: float, away: float, **kw: object) -> dict:
    """One finished Premier League match row; override fields with kwargs."""
    row = {
        "match_id": match_id, "snapshot_gw": 1, "gameweek": 1, "tournament": "prem",
        "kickoff_time": "2026-08-21T19:00:00", "home_team": home, "away_team": away,
        "home_team_elo": 1600.0, "away_team_elo": 1500.0, "home_score": 2.0, "away_score": 1.0,
        "home_expected_goals_xg": 1.5, "away_expected_goals_xg": 0.7,
        "home_non_penalty_xg": 1.2, "away_non_penalty_xg": 0.7,
        "finished": True,
    }
    row.update(kw)
    return row


def matches_frame(rows: list[dict]) -> pd.DataFrame:
    """Matches frame (with the snapshot_gw column ingest adds)."""
    df = blank_frame("matches", rows)
    df["snapshot_gw"] = [r.get("snapshot_gw", 1) for r in rows]
    return df


def pms_row(player_id: int, match_id: str, minutes: float, **kw: object) -> dict:
    """One playermatchstats row for a player who has played; override with kwargs."""
    row = {
        "player_id": player_id, "match_id": match_id, "snapshot_gw": 1, "minutes_played": minutes,
        "goals": 0.0, "assists": 0.0, "total_shots": 1.0, "xg": 0.1, "xa": 0.05,
        "tackles": 2.0, "tackles_won": 2.0, "interceptions": 1.0, "clearances": 1.0,
        "blocks": 0.0, "recoveries": 3.0, "saves": 0.0, "penalties_scored": 0.0,
        "penalties_missed": 0.0,
    }
    row.update(kw)
    return row


def pms_frame(rows: list[dict]) -> pd.DataFrame:
    """playermatchstats frame (with the snapshot_gw column ingest adds)."""
    df = blank_frame("playermatchstats", rows)
    df["snapshot_gw"] = [r.get("snapshot_gw", 1) for r in rows]
    return df


def player_row(player_id: int, team_code: int, **kw: object) -> dict:
    """One players.csv row."""
    row = {
        "player_code": 1000 + player_id, "player_id": player_id, "web_name": f"P{player_id}",
        "team_code": team_code, "position": "Midfielder", "snapshot_gw": 1,
    }
    row.update(kw)
    return row


def players_frame(rows: list[dict]) -> pd.DataFrame:
    """players frame (with the snapshot_gw column ingest adds)."""
    df = blank_frame("players", rows)
    df["snapshot_gw"] = [r.get("snapshot_gw", 1) for r in rows]
    return df


POSITIONS = {"Goalkeeper": "GKP", "Defender": "DEF", "Midfielder": "MID", "Forward": "FWD"}
FILL = [
    "goals", "assists", "xg", "xa", "pens_scored", "pens_missed", "tackles",
    "interceptions", "clearances", "blocks", "recoveries", "saves",
]
# id 1 has code 3 and id 3 has code 1: a join on id instead of code swaps the clubs.
SWAPPED = teams_frame([(1, 3), (3, 1), (2, 7), (7, 2)])


def pm_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    matches = matches_frame([
        match_row("m1", 3.0, 99.0),
        match_row("m2", 7.0, 99.0, snapshot_gw=2, gameweek=2),
    ])
    players = players_frame([
        player_row(10, 3), player_row(11, 7),
        player_row(10, 7, snapshot_gw=2), player_row(11, 7, snapshot_gw=2),
    ])
    return matches, players


def complete_all(matches: pd.DataFrame) -> pd.Series:
    """A completeness flag that is true for every match, for tests that are about something else."""
    return pd.Series(True, index=matches.index)
