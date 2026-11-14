"""Schemas of the published CSVs the export writes (docs/data_contract.md).

Each entry is (column, kind, nullable), in contract order. A test parses the contract and
compares the names and order.
"""

from __future__ import annotations

OUTPUT_SCHEMA: dict[str, list[tuple[str, str, bool]]] = {
    "players": [
        ("player_id", "int", False), ("web_name", "str", False), ("team", "str", False),
        ("position", "str", False), ("price_m", "float", False), ("status", "str", False),
        ("chance_next", "int", True), ("news", "str", True), ("selected_pct", "float", False),
        ("minutes", "int", False), ("starts", "int", False), ("total_points", "int", False),
        ("ppg", "float", False), ("xg90", "float", False), ("xa90", "float", False),
        ("dc90", "float", False), ("pen_taker", "bool", False),
        ("net_transfers_gw", "int", False), ("price_change_gw", "float", False),
        ("price_change_start", "float", False),
    ],
    "fixture_difficulty": [
        ("team_id", "int", False), ("team", "str", False), ("match_id", "str", False),
        ("gw", "int", False), ("opponent_id", "int", False), ("opponent", "str", False),
        ("home", "bool", False), ("lambda_for", "float", False),
        ("lambda_against", "float", False), ("p_cs", "float", False),
    ],
    "elo_ratings": [
        ("team_id", "int", False), ("match_id", "str", False), ("season", "str", False),
        ("gw", "int", False), ("kickoff_utc", "str", False), ("elo_before", "float", False),
        ("elo_after", "float", False),
    ],
    "meta": [
        ("run_utc", "str", False), ("upstream_commit", "str", False),
        ("current_gw", "int", False), ("next_gw", "int", False),
        ("next_deadline_utc", "str", False), ("model_version", "str", False),
        ("max_horizon", "int", False), ("backtest_mae_model", "float", True),
        ("backtest_mae_ep_next", "float", True), ("status", "str", False),
    ],
}

# The published unique key of each file; players and meta are one row per player or per run.
OUTPUT_KEYS: dict[str, list[str]] = {
    "players": ["player_id"],
    "fixture_difficulty": ["team_id", "match_id"],
    "elo_ratings": ["season", "team_id", "match_id"],
    "meta": ["run_utc"],
}


def output_columns(name: str) -> list[str]:
    """Ordered column names of a published file."""
    return [c for c, _, _ in OUTPUT_SCHEMA[name]]
