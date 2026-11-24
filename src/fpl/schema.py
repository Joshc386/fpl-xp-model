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
            "home_non_penalty_xg", "away_non_penalty_xg", "home_total_shots", "away_total_shots",
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
            "corners_and_indirect_freekicks_order", "ep_next", "cost_change_start",
            "cost_change_event", "transfers_in_event", "transfers_out_event",
        ],
    },
    "playermatchstats": {
        "str": ["match_id"],
        "bool": [],
        "num": [
            "player_id", "minutes_played", "goals", "assists", "total_shots", "xg", "xa",
            "tackles", "tackles_won", "interceptions", "clearances", "blocks", "recoveries",
            "saves", "penalties_scored", "penalties_missed", "start_min", "finish_min",
        ],
    },
    # Shots (Premier League complete matches only are built) and, for seasons whose spells
    # come from it, incidents (substitutions and red cards).
    "shots": {
        "str": ["match_id", "situation", "outcome"],
        "bool": ["is_home"],
        "num": ["shot_index", "minute", "added_time", "player_id", "xg"],
    },
    "incidents": {
        "str": ["match_id", "incident_type", "card_type"],
        "bool": [],
        "num": ["minute", "added_time", "player_id", "secondary_player_id"],
    },
    # Master file (live mode only): the deadline clock.
    "gameweek_summaries": {"str": ["deadline_time"], "bool": [], "num": ["id"]},
    "player_gameweek_stats": {
        "str": [],
        "bool": [],
        "num": [
            "id", "gw", "event_points", "minutes", "starts", "bonus", "bps", "goals_scored",
            "assists", "yellow_cards",
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
    "away_expected_goals_xg", "home_non_penalty_xg", "away_non_penalty_xg", "home_total_shots",
    "away_total_shots",
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
        ("price_change_start_tenths", "int", False), ("price_change_gw_tenths", "int", False),
        ("transfers_in_gw", "int", False), ("transfers_out_gw", "int", False),
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
        ("bonus", "int", False), ("bps", "int", False), ("fpl_goals", "int", False),
        ("fpl_assists", "int", False), ("yellow", "int", False),
        ("red", "int", False), ("own_goals", "int", False),
        ("goals_conceded", "int", False), ("tackles", "int", False),
        ("cbi", "int", False), ("recoveries", "int", False),
        ("defensive_contribution", "int", False), ("price_tenths", "int", False),
        ("selected_pct", "float", False), ("transfers_in", "int", False),
        ("transfers_out", "int", False),
    ],
    "fact_shot": [
        ("match_id", "str", False), ("shot_index", "int", False), ("team_id", "int", False),
        ("player_id", "int", True), ("minute", "int", False), ("added_time", "int", True),
        ("clock", "float", False), ("situation", "str", False), ("outcome", "str", False),
        ("xg", "float", False), ("is_penalty", "bool", False), ("is_own_goal", "bool", False),
    ],
    "fact_player_spell": [
        ("player_id", "int", False), ("team_id", "int", False), ("match_id", "str", False),
        ("spell_start", "float", False), ("spell_end", "float", True),
        ("spell_repaired", "bool", False),
    ],
}

# Natural key of each processed table.
TABLE_KEYS: dict[str, list[str]] = {
    "dim_player": ["player_id"],
    "dim_team": ["team_id"],
    "fact_fixture": ["match_id"],
    "fact_player_match": ["player_id", "match_id"],
    "fact_player_gw": ["player_id", "gw"],
    "fact_shot": ["match_id", "shot_index"],
    "fact_player_spell": ["player_id", "match_id"],
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
    return check_schema(df, table, PROCESSED_SCHEMA[table])


def check_schema(df: pd.DataFrame, table: str, spec: list[tuple[str, str, bool]]) -> list[str]:
    """Problems with `df` against `spec` (column, kind, nullable), in order; empty if fine."""
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
