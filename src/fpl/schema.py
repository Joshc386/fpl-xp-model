"""Schemas: the raw upstream columns the pipeline reads, and the processed tables.

`PROCESSED_SCHEMA` mirrors docs/data_contract.md; a test parses the contract and
compares column names and order. `RAW_SCHEMA` lists only the upstream columns the
pipeline uses, which is what input validation requires to be present. Upstream
may add columns freely; it may not drop or rename these.
"""

from __future__ import annotations

import pandas as pd

# file -> {"str": text columns, "bool": flag columns, "num": float columns}
RAW_SCHEMA: dict[str, dict[str, list[str]]] = {
    "matches": {
        "str": ["match_id", "kickoff_time", "tournament"],
        "bool": ["finished"],
        "num": [
            "gameweek", "home_team", "away_team", "home_team_elo", "away_team_elo",
            "home_score", "away_score", "home_expected_goals_xg", "away_expected_goals_xg",
            "home_non_penalty_xg", "away_non_penalty_xg",
        ],
    },
    "fixtures": {"str": ["match_id"], "bool": [], "num": ["gameweek"]},
    "players": {
        "str": ["web_name", "position"],
        "bool": [],
        "num": ["player_code", "player_id", "team_code"],
    },
    "teams": {"str": ["name", "short_name"], "bool": [], "num": ["code", "id"]},
    "playerstats": {
        "str": ["status", "news"],
        "bool": [],
        "num": [
            "id", "gw", "chance_of_playing_next_round", "now_cost", "selected_by_percent",
            "penalties_order", "direct_freekicks_order",
            "corners_and_indirect_freekicks_order", "ep_next",
        ],
    },
    "playermatchstats": {
        "str": ["match_id"],
        "bool": [],
        "num": [
            "player_id", "minutes_played", "goals", "assists", "total_shots", "xg", "xa",
            "tackles", "tackles_won", "interceptions", "clearances", "blocks", "recoveries",
            "saves", "penalties_scored", "penalties_missed",
        ],
    },
    # Master file (live mode only): the deadline clock.
    "gameweek_summaries": {"str": ["deadline_time"], "bool": [], "num": ["id"]},
    "player_gameweek_stats": {
        "str": [],
        "bool": [],
        "num": [
            "id", "gw", "event_points", "minutes", "starts", "bonus", "bps", "yellow_cards",
            "red_cards", "own_goals", "goals_conceded", "tackles",
            "clearances_blocks_interceptions", "recoveries", "defensive_contribution", "now_cost",
            "selected_by_percent",
            "transfers_in_event", "transfers_out_event",
        ],
    },
}

# matches.csv columns that carry a result, xG or upstream Elo. The loader blanks them (and
# `finished`) for matches in gameweeks after the as-of gameweek, which are schedule only.
RESULT_COLUMNS: list[str] = [
    "home_team_elo", "away_team_elo", "home_score", "away_score", "home_expected_goals_xg",
    "away_expected_goals_xg", "home_non_penalty_xg", "away_non_penalty_xg",
]

# table -> [(column, kind, nullable)]. Kinds: int, float, bool, str. A nullable int
# is stored as pandas Int64.
Col = tuple[str, str, bool]
PROCESSED_SCHEMA: dict[str, list[Col]] = {
    "dim_player": [
        ("player_id", "int", False), ("player_code", "int", False), ("web_name", "str", False),
        ("team_id", "int", False), ("position", "str", False), ("price_tenths", "int", False),
        ("status", "str", False), ("chance_next", "int", True), ("news", "str", True),
        ("selected_pct", "float", False), ("pen_order", "int", True),
        ("fk_order", "int", True), ("corner_order", "int", True), ("ep_next", "float", True),
    ],
    "dim_team": [
        ("team_id", "int", False), ("team_code", "int", False), ("name", "str", False),
        ("short_name", "str", False), ("upstream_elo", "float", True),
    ],
    "fact_fixture": [
        ("match_id", "str", False), ("season", "str", False), ("gw", "int", False),
        ("kickoff_utc", "str", False), ("tournament", "str", False),
        ("home_team_id", "int", True), ("away_team_id", "int", True),
        ("home_upstream_elo", "float", True), ("away_upstream_elo", "float", True),
        ("finished", "bool", False), ("stats_complete", "bool", False),
        ("home_xg", "float", True), ("away_xg", "float", True),
        ("home_npxg", "float", True), ("away_npxg", "float", True),
        ("home_goals", "int", True), ("away_goals", "int", True),
    ],
    "fact_player_match": [
        ("player_id", "int", False), ("team_id", "int", False), ("match_id", "str", False),
        ("minutes", "int", False), ("goals", "int", False), ("assists", "int", False),
        ("xg", "float", False), ("xa", "float", False), ("pens_scored", "int", False),
        ("pens_missed", "int", False), ("tackles", "int", False),
        ("interceptions", "int", False), ("clearances", "int", False), ("blocks", "int", False),
        ("recoveries", "int", False), ("saves", "int", False),
    ],
    "fact_player_gw": [
        ("player_id", "int", False), ("team_id", "int", True), ("season", "str", False),
        ("gw", "int", False),
        ("points", "int", False), ("minutes", "int", False), ("starts", "int", False),
        ("bonus", "int", False), ("bps", "int", False), ("yellow", "int", False),
        ("red", "int", False), ("own_goals", "int", False),
        ("goals_conceded", "int", False), ("tackles", "int", False),
        ("cbi", "int", False), ("recoveries", "int", False),
        ("defensive_contribution", "int", False), ("price_tenths", "int", False),
        ("selected_pct", "float", False), ("transfers_in", "int", False),
        ("transfers_out", "int", False),
    ],
}

# Natural key of each processed table.
TABLE_KEYS: dict[str, list[str]] = {
    "dim_player": ["player_id"],
    "dim_team": ["team_id"],
    "fact_fixture": ["match_id"],
    "fact_player_match": ["player_id", "match_id"],
    "fact_player_gw": ["player_id", "gw"],
}


# fact_player_match column -> playermatchstats column it is read from. Only
# `tackles` varies by season (see `fill_sources`).
PMS_SOURCE: dict[str, str] = {
    "goals": "goals", "assists": "assists", "xg": "xg", "xa": "xa",
    "pens_scored": "penalties_scored", "pens_missed": "penalties_missed",
    "tackles": "tackles", "interceptions": "interceptions", "clearances": "clearances",
    "blocks": "blocks", "recoveries": "recoveries", "saves": "saves",
}


def fill_sources(tackles_column: str) -> dict[str, str]:
    """PMS_SOURCE with `tackles` pointed at the season's FPL tackle column."""
    return PMS_SOURCE | {"tackles": tackles_column}


def raw_columns(file: str) -> list[str]:
    """Every upstream column of `file` that the pipeline requires."""
    spec = RAW_SCHEMA[file]
    return spec["str"] + spec["bool"] + spec["num"]


def raw_dtypes(file: str) -> dict[str, str]:
    """Explicit read dtypes: text as str, flags as nullable boolean, numbers as float64.

    Numbers are read as float64 because upstream leaves blanks in count columns;
    a header-only file would otherwise load as object and poison a concatenation.
    """
    spec = RAW_SCHEMA[file]
    return (
        dict.fromkeys(spec["str"], "str")
        | dict.fromkeys(spec["bool"], "boolean")
        | dict.fromkeys(spec["num"], "float64")
    )


def column_names(table: str) -> list[str]:
    """Ordered column names of a processed table."""
    return [c for c, _, _ in PROCESSED_SCHEMA[table]]


def expected_dtype(kind: str, nullable: bool) -> str:
    """The pandas dtype name a processed column must have."""
    if kind == "int":
        return "Int64" if nullable else "int64"
    return {"float": "float64", "bool": "bool", "str": "str"}[kind]


def _dtype_ok(series: pd.Series, kind: str, nullable: bool) -> bool:
    if kind == "str":
        return bool(pd.api.types.is_string_dtype(series.dtype))
    return str(series.dtype) == expected_dtype(kind, nullable)


def check_table_schema(df: pd.DataFrame, table: str) -> list[str]:
    """Problems with a processed table's columns, dtypes and nulls; empty if it is fine."""
    spec = PROCESSED_SCHEMA[table]
    names = [c for c, _, _ in spec]
    if list(df.columns) != names:
        return [f"{table}: columns {list(df.columns)} differ from the contract {names}"]
    problems = []
    for col, kind, nullable in spec:
        if not _dtype_ok(df[col], kind, nullable):
            want = expected_dtype(kind, nullable)
            problems.append(f"{table}.{col}: dtype {df[col].dtype}, expected {want}")
        elif not nullable and df[col].isna().any():
            problems.append(f"{table}.{col}: {int(df[col].isna().sum())} null values")
    return problems
