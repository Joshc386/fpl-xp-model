"""Contract schema tests: the code's table schemas must match docs/data_contract.md."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from fpl.schema import PROCESSED_SCHEMA, check_table_schema, column_names

CONTRACT = Path(__file__).resolve().parents[1] / "docs" / "data_contract.md"


def contract_columns() -> dict[str, list[str]]:
    """Parse the processed-table rows of the contract's first table."""
    out: dict[str, list[str]] = {}
    for line in CONTRACT.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\| `(dim_\w+|fact_\w+)` \|[^|]*\|(.*)\|\s*$", line)
        if m:
            out[m.group(1)] = re.findall(r"`(\w+)`", m.group(2))
    return out


def test_every_contract_table_is_in_the_code_schema_in_the_same_column_order() -> None:
    expected = contract_columns()
    assert set(expected) == {
        "dim_player", "dim_team", "fact_fixture", "fact_player_match", "fact_player_gw",
    }
    for table, cols in expected.items():
        assert column_names(table) == cols, table


def test_nullable_columns_are_the_contract_ones_plus_the_proposed_dim_player_ones() -> None:
    nullable = {t: {c for c, _, n in spec if n} for t, spec in PROCESSED_SCHEMA.items()}
    assert nullable["fact_fixture"] == {
        "home_team_id", "away_team_id", "home_upstream_elo", "away_upstream_elo",
        "home_xg", "away_xg", "home_npxg", "away_npxg", "home_goals", "away_goals",
    }
    assert nullable["fact_player_match"] == set()
    assert nullable["dim_team"] == {"upstream_elo"}
    assert nullable["fact_player_gw"] == set()
    # Not listed in the contract; proposed in the task 1 report.
    assert nullable["dim_player"] == {
        "chance_next", "news", "pen_order", "fk_order", "corner_order", "ep_next",
    }


def valid_dim_team() -> pd.DataFrame:
    """A one-row dim_team that satisfies the schema."""
    return pd.DataFrame({
        "team_id": pd.array([1], dtype="int64"), "team_code": pd.array([3], dtype="int64"),
        "name": ["Arsenal"], "short_name": ["ARS"], "upstream_elo": [float("nan")],
    })


def test_a_valid_table_has_no_problems() -> None:
    assert check_table_schema(valid_dim_team(), "dim_team") == []


def test_missing_extra_and_reordered_columns_are_reported() -> None:
    df = valid_dim_team()
    assert check_table_schema(df.drop(columns="name"), "dim_team")
    assert check_table_schema(df.assign(extra=1), "dim_team")
    assert check_table_schema(df[list(reversed(df.columns))], "dim_team")


def test_wrong_dtype_is_reported() -> None:
    df = valid_dim_team().assign(team_id=1.5)
    problems = check_table_schema(df, "dim_team")
    assert any("team_id" in p and "dtype" in p for p in problems)


def test_null_in_a_non_nullable_column_is_reported_but_not_in_a_nullable_one() -> None:
    df = valid_dim_team()
    df.loc[0, "name"] = None
    problems = check_table_schema(df, "dim_team")
    assert any("name" in p and "null" in p for p in problems)
    assert not any("upstream_elo" in p for p in problems)


def test_unknown_table_raises() -> None:
    with pytest.raises(KeyError):
        check_table_schema(valid_dim_team(), "dim_nothing")
