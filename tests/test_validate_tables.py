"""Rule 15 guards, cross-season checks and processed-table validation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fpl.clean import build_season
from fpl.ingest import RawSeason
from fpl.validate import ValidationError, check_match_ids_disjoint, check_rule15_guards
from fpl.validate_tables import validate_tables
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
    validate_tables(tables, "prem")


def test_table_validation_catches_a_schema_break(tables: dict[str, pd.DataFrame]) -> None:
    tables["dim_team"] = tables["dim_team"].drop(columns="name")
    with pytest.raises(ValidationError, match="dim_team"):
        validate_tables(tables, "prem")


def test_table_validation_catches_duplicate_keys(tables: dict[str, pd.DataFrame]) -> None:
    pm = tables["fact_player_match"]
    tables["fact_player_match"] = pd.concat([pm, pm.head(1)], ignore_index=True)
    with pytest.raises(ValidationError, match="fact_player_match"):
        validate_tables(tables, "prem")


def test_table_validation_catches_an_orphan_foreign_key(tables: dict[str, pd.DataFrame]) -> None:
    tables["fact_player_match"].loc[0, "team_id"] = 9_999
    with pytest.raises(ValidationError, match="team_id"):
        validate_tables(tables, "prem")


def test_table_validation_catches_an_unknown_club_in_fact_player_gw(
    tables: dict[str, pd.DataFrame],
) -> None:
    tables["fact_player_gw"].loc[0, "team_id"] = 9_999
    with pytest.raises(ValidationError, match="fact_player_gw.team_id"):
        validate_tables(tables, "prem")


def test_a_null_club_in_fact_player_gw_is_allowed(tables: dict[str, pd.DataFrame]) -> None:
    tables["fact_player_gw"].loc[0, "team_id"] = pd.NA
    validate_tables(tables, "prem")


def test_table_validation_catches_a_result_on_an_unfinished_match(
    tables: dict[str, pd.DataFrame],
) -> None:
    fx = tables["fact_fixture"]
    fx.loc[fx.index[~fx.finished][0], "home_goals"] = 0
    with pytest.raises(ValidationError, match="unfinished"):
        validate_tables(tables, "prem")


def test_table_validation_catches_xg_on_an_incomplete_match(
    tables: dict[str, pd.DataFrame],
) -> None:
    fx = tables["fact_fixture"]
    fx.loc[fx.index[~fx.stats_complete][0], "home_xg"] = 1.0
    with pytest.raises(ValidationError, match="incomplete"):
        validate_tables(tables, "prem")


def test_table_validation_catches_a_complete_match_that_is_not_finished(
    tables: dict[str, pd.DataFrame],
) -> None:
    fx = tables["fact_fixture"]
    fx.loc[fx.index[~fx.finished][0], "stats_complete"] = True
    with pytest.raises(ValidationError, match="complete matches that are not finished"):
        validate_tables(tables, "prem")


def test_table_validation_catches_a_finished_match_without_a_score(
    tables: dict[str, pd.DataFrame],
) -> None:
    fx = tables["fact_fixture"]
    fx.loc[fx.index[fx.finished][0], "home_goals"] = pd.NA
    with pytest.raises(ValidationError, match="without a score"):
        validate_tables(tables, "prem")


def test_a_complete_premier_league_match_without_npxg_fails(
    tables: dict[str, pd.DataFrame],
) -> None:
    fx = tables["fact_fixture"]
    idx = fx.index[fx.stats_complete & (fx.tournament == "prem")][0]
    fx.loc[idx, "away_npxg"] = np.nan
    with pytest.raises(ValidationError, match="without npxG"):
        validate_tables(tables, "prem")


def test_a_complete_cup_match_without_npxg_is_allowed(tables: dict[str, pd.DataFrame]) -> None:
    fx = tables["fact_fixture"]
    cup = fx.index[fx.stats_complete & (fx.tournament != "prem")]
    assert len(cup)
    fx.loc[cup, ["home_npxg", "away_npxg"]] = np.nan
    validate_tables(tables, "prem")


def test_the_premier_league_tag_for_the_npxg_check_comes_from_the_caller(
    tables: dict[str, pd.DataFrame],
) -> None:
    fx = tables["fact_fixture"]
    fx.loc[fx.index[fx.stats_complete & (fx.tournament == "prem")][0], "away_npxg"] = np.nan
    fx[["home_upstream_elo", "away_upstream_elo"]] = np.nan  # with no league, no row may have Elo
    validate_tables(tables, "no-such-tag")


def test_table_validation_catches_a_player_row_for_a_club_not_in_the_match(
    tables: dict[str, pd.DataFrame],
) -> None:
    pm, fx = tables["fact_player_match"], tables["fact_fixture"]
    match = fx.set_index("match_id").loc[pm.match_id.iloc[0]]
    other = next(t for t in tables["dim_team"].team_id
                 if t not in (match.home_team_id, match.away_team_id))
    pm.loc[0, "team_id"] = other
    with pytest.raises(ValidationError, match="club not in the match"):
        validate_tables(tables, "prem")


def test_table_validation_catches_upstream_elo_on_a_cup_row(
    tables: dict[str, pd.DataFrame],
) -> None:
    fx = tables["fact_fixture"]
    fx.loc[fx.index[fx.tournament != "prem"][0], "home_upstream_elo"] = 1871.97
    with pytest.raises(ValidationError, match="Elo on cup"):
        validate_tables(tables, "prem")


def test_table_validation_catches_a_wrong_club_in_a_match_whose_opponent_has_no_team_id(
    tables: dict[str, pd.DataFrame],
) -> None:
    # A European or cup opponent outside the league has a null team_id; the comparison with it
    # is NA, which must count as "not the club" rather than hide the row.
    fx, pm = tables["fact_fixture"], tables["fact_player_match"]
    cup = fx[fx.home_team_id.isna() | fx.away_team_id.isna()].match_id
    row = pm.index[pm.match_id.isin(cup)][0]
    match = fx.set_index("match_id").loc[pm.loc[row, "match_id"]]
    clubs = [x for x in (match.home_team_id, match.away_team_id) if not pd.isna(x)]
    pm.loc[row, "team_id"] = next(t for t in tables["dim_team"].team_id if t not in clubs)
    with pytest.raises(ValidationError, match="club not in the match"):
        validate_tables(tables, "prem")
