"""The published-output schemas must match the Published outputs table in the contract."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fpl.output_schema import OUTPUT_KEYS, OUTPUT_SCHEMA, output_columns

CONTRACT = Path(__file__).resolve().parents[1] / "docs" / "data_contract.md"
FILES = ["players", "fixture_difficulty", "elo_ratings", "meta"]


def contract_output_columns() -> dict[str, list[str]]:
    """The columns of each published file, from the contract's Published outputs table."""
    out: dict[str, list[str]] = {}
    for line in CONTRACT.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\| `(\w+)\.csv` \|[^|]*\|(.*)\|\s*$", line)
        if m:
            out[m.group(1)] = re.findall(r"`(\w+)`", m.group(2))
    return out


@pytest.mark.parametrize("name", FILES)
def test_columns_and_order_match_the_contract(name: str) -> None:
    assert output_columns(name) == contract_output_columns()[name]


def test_keys_are_columns_of_their_file() -> None:
    for name in FILES:
        assert set(OUTPUT_KEYS[name]) <= set(output_columns(name))


def test_only_the_contract_nullable_columns_are_nullable() -> None:
    nullable = {n: {c for c, _, null in OUTPUT_SCHEMA[n] if null} for n in FILES}
    assert nullable["players"] == {"chance_next", "news"}
    assert nullable["meta"] == {"backtest_mae_model", "backtest_mae_ep_next"}
    assert nullable["fixture_difficulty"] == nullable["elo_ratings"] == set()
