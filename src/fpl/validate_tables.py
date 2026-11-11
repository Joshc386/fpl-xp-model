"""Validation of the processed tables: schema, keys, foreign keys, results, clubs, Elo."""

from __future__ import annotations

import pandas as pd

from fpl.schema import TABLE_KEYS, check_table_schema
from fpl.validate import ValidationError, key_problems

# Fact tables may hold players who have since left the league, so player_id is not
# required to be in dim_player (a snapshot of the current players).
_FOREIGN_KEYS = (
    ("fact_fixture", "home_team_id", "dim_team", "team_id"),
    ("fact_fixture", "away_team_id", "dim_team", "team_id"),
    ("dim_player", "team_id", "dim_team", "team_id"),
    ("fact_player_match", "match_id", "fact_fixture", "match_id"),
    ("fact_player_match", "team_id", "dim_team", "team_id"),
    ("fact_player_gw", "team_id", "dim_team", "team_id"),
)


def _fixture_result_problems(fx: pd.DataFrame, prem_tag: str) -> list[str]:
    """Scores only on finished matches, xG only on complete ones, npxG on complete PL ones."""
    goals, xg = ["home_goals", "away_goals"], ["home_xg", "away_xg", "home_npxg", "away_npxg"]
    out = []
    if fx.loc[~fx.finished, goals].notna().any().any():
        out.append("fact_fixture: scores present on unfinished matches")
    if fx.loc[fx.finished, goals].isna().any().any():
        out.append("fact_fixture: finished matches without a score")
    if fx.loc[~fx.stats_complete, xg].notna().any().any():
        out.append("fact_fixture: xG present on incomplete matches")
    if (fx.stats_complete & ~fx.finished).any():
        out.append("fact_fixture: complete matches that are not finished")
    # npxG may be null on complete cup and European matches, never on Premier League ones.
    prem = fx.stats_complete & (fx.tournament == prem_tag)
    if fx.loc[prem, ["home_npxg", "away_npxg"]].isna().any().any():
        out.append(f"fact_fixture: complete {prem_tag} matches without npxG")
    return out


def _club_and_elo_problems(tables: dict[str, pd.DataFrame], prem_tag: str) -> list[str]:
    """Each player-match row is for one of the match's clubs; upstream Elo only on league rows."""
    fx = tables["fact_fixture"]
    out = []
    clubs = tables["fact_player_match"].merge(
        fx[["match_id", "home_team_id", "away_team_id"]], on="match_id", how="left"
    )
    # A European opponent has a null team_id, so compare with NA read as "not the club".
    in_match = (clubs.team_id == clubs.home_team_id).fillna(False) | (
        clubs.team_id == clubs.away_team_id
    ).fillna(False)
    stray = ~in_match
    if stray.any():
        out.append(f"fact_player_match: {int(stray.sum())} rows for a club not in the match")
    cup_elo = fx.loc[fx.tournament != prem_tag, ["home_upstream_elo", "away_upstream_elo"]]
    if cup_elo.notna().any().any():
        out.append("fact_fixture: upstream Elo on cup or European rows")
    return out


def validate_tables(tables: dict[str, pd.DataFrame], prem_tag: str) -> None:
    """Check processed tables: schema, unique keys, foreign keys, results only when finished."""
    problems: list[str] = []
    for name, df in tables.items():
        problems += check_table_schema(df, name)
        if not problems:
            problems += key_problems(df, TABLE_KEYS[name], name)
    if not problems:
        for table, col, ref, ref_col in _FOREIGN_KEYS:
            orphans = int((~tables[table][col].dropna().isin(tables[ref][ref_col])).sum())
            if orphans:
                problems.append(f"{table}.{col}: {orphans} values not in {ref}.{ref_col}")
        problems += _fixture_result_problems(tables["fact_fixture"], prem_tag)
        problems += _club_and_elo_problems(tables, prem_tag)
    if problems:
        raise ValidationError(problems)
