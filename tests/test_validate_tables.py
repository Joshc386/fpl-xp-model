"""Rule 15 guards, cross-season checks and processed-table validation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fpl.clean import build_season
from fpl.ingest import RawSeason
from fpl.validate import (
    ValidationError,
    check_match_ids_disjoint,
    check_rule15_guards,
    validate_tables,
)
from helpers import FILL, pms_frame, pms_row

# ---- rule 15 guards ----------------------------------------------------------------------------

def test_guards_pass_on_a_healthy_season() -> None:
    pms = pms_frame([pms_row(1, "m", 90.0), pms_row(2, "m", 0.0, xg=np.nan, total_shots=np.nan)])
    assert check_rule15_guards(pms, "tackles", FILL) == []


def test_guard_fails_when_a_listed_column_is_empty_for_the_whole_season() -> None:
    pms = pms_frame([pms_row(1, "m", 90.0, interceptions=np.nan)])
    out = check_rule15_guards(pms, "tackles", FILL)
    assert len(out) == 1
    assert "interceptions" in out[0]


def test_guard_checks_the_source_column_that_is_actually_mapped() -> None:
    pms = pms_frame([pms_row(1, "m", 90.0, tackles=np.nan, tackles_won=4.0)])
    assert check_rule15_guards(pms, "tackles_won", FILL) == []
    out = check_rule15_guards(pms, "tackles", FILL)
    assert any("tackles" in p and "empty" in p for p in out)


def test_guard_fails_on_a_blank_xg_beside_shots_but_not_beside_none() -> None:
    ok = pms_frame([pms_row(1, "m", 90.0), pms_row(2, "m", 90.0, xg=np.nan, total_shots=0.0)])
    assert check_rule15_guards(ok, "tackles", FILL) == []
    bad = pms_frame([pms_row(1, "m", 90.0), pms_row(2, "m", 90.0, xg=np.nan, total_shots=3.0)])
    assert any("xg" in p and "total_shots" in p for p in check_rule15_guards(bad, "tackles", FILL))


def test_guards_ignore_an_empty_frame() -> None:
    assert check_rule15_guards(pms_frame([]), "tackles", FILL) == []


# ---- across seasons and processed tables -------------------------------------------------------

def test_match_ids_must_not_repeat_across_seasons(
    raw_2526: RawSeason, raw_2627: RawSeason
) -> None:
    check_match_ids_disjoint([raw_2526, raw_2627])
    raw_2627.matches.loc[0, "match_id"] = raw_2526.matches.match_id.iloc[0]
    with pytest.raises(ValidationError, match="match_id"):
        check_match_ids_disjoint([raw_2526, raw_2627])


@pytest.fixture
def tables(raw_2627: RawSeason, cfg: dict) -> dict[str, pd.DataFrame]:
    return build_season(raw_2627, cfg).tables


def test_built_tables_pass_table_validation(tables: dict[str, pd.DataFrame]) -> None:
    validate_tables(tables)


def test_table_validation_catches_a_schema_break(tables: dict[str, pd.DataFrame]) -> None:
    tables["dim_team"] = tables["dim_team"].drop(columns="name")
    with pytest.raises(ValidationError, match="dim_team"):
        validate_tables(tables)


def test_table_validation_catches_duplicate_keys(tables: dict[str, pd.DataFrame]) -> None:
    pm = tables["fact_player_match"]
    tables["fact_player_match"] = pd.concat([pm, pm.head(1)], ignore_index=True)
    with pytest.raises(ValidationError, match="fact_player_match"):
        validate_tables(tables)


def test_table_validation_catches_an_orphan_foreign_key(tables: dict[str, pd.DataFrame]) -> None:
    tables["fact_player_match"].loc[0, "team_id"] = 9_999
    with pytest.raises(ValidationError, match="team_id"):
        validate_tables(tables)


def test_table_validation_catches_a_result_on_an_unfinished_match(
    tables: dict[str, pd.DataFrame],
) -> None:
    fx = tables["fact_fixture"]
    fx.loc[fx.index[~fx.finished][0], "home_goals"] = 0
    with pytest.raises(ValidationError, match="unfinished"):
        validate_tables(tables)


def test_table_validation_catches_xg_on_an_incomplete_match(
    tables: dict[str, pd.DataFrame],
) -> None:
    fx = tables["fact_fixture"]
    fx.loc[fx.index[~fx.stats_complete][0], "home_xg"] = 1.0
    with pytest.raises(ValidationError, match="incomplete"):
        validate_tables(tables)


def test_table_validation_catches_a_complete_match_that_is_not_finished(
    tables: dict[str, pd.DataFrame],
) -> None:
    fx = tables["fact_fixture"]
    fx.loc[fx.index[~fx.finished][0], "stats_complete"] = True
    with pytest.raises(ValidationError, match="complete matches that are not finished"):
        validate_tables(tables)
