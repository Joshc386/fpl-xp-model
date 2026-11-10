"""Input and table validation: every check must be able to fail the run."""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest

from fpl.ingest import RawSeason
from fpl.validate import (
    ValidationError,
    validate_inputs,
)


@pytest.fixture
def small_cfg(cfg: dict) -> dict:
    """Config with the full-season bounds relaxed to suit the 9-match samples."""
    out = copy.deepcopy(cfg)
    out["validation"].update(
        prem_matches_rows=[1, 380], matches_rows=[1, 700], players_rows_per_snapshot=[1, 1000],
        playerstats_rows_snapshot=[1, 1000], player_gameweek_stats_rows_per_gw=[1, 1000],
    )
    return out


def season_cfg(cfg: dict, season: str) -> dict:
    return next(s for s in cfg["seasons"] if s["id"] == season) | {"gameweeks": 3}


def problems(raw: RawSeason, small_cfg: dict) -> str:
    """Run validate_inputs and return the joined problem text ('' if it passes)."""
    try:
        validate_inputs(raw, small_cfg, season_cfg(small_cfg, raw.season))
    except ValidationError as exc:
        return "; ".join(exc.problems)
    return ""


def test_the_real_samples_pass(raw_2627: RawSeason, small_cfg: dict) -> None:
    assert problems(raw_2627, small_cfg) == ""


def test_a_missing_expected_file_fails(raw_2627: RawSeason, small_cfg: dict) -> None:
    raw_2627.missing_files = ["GW2/matches.csv"]
    assert "missing file" in problems(raw_2627, small_cfg)


def test_a_missing_required_column_fails(raw_2627: RawSeason, small_cfg: dict) -> None:
    raw_2627.file_columns["GW1/matches.csv"].remove("home_team")
    assert "home_team" in problems(raw_2627, small_cfg)


def test_a_duplicate_match_id_fails(raw_2627: RawSeason, small_cfg: dict) -> None:
    raw_2627.matches = pd.concat([raw_2627.matches, raw_2627.matches.head(1)], ignore_index=True)
    assert "match_id" in problems(raw_2627, small_cfg)


def test_a_null_key_fails(raw_2627: RawSeason, small_cfg: dict) -> None:
    raw_2627.playermatchstats.loc[0, "player_id"] = np.nan
    assert "player_id" in problems(raw_2627, small_cfg)


def test_a_duplicate_player_match_key_fails(raw_2627: RawSeason, small_cfg: dict) -> None:
    pms = raw_2627.playermatchstats
    raw_2627.playermatchstats = pd.concat([pms, pms.head(1)], ignore_index=True)
    assert "playermatchstats" in problems(raw_2627, small_cfg)


def test_duplicate_teams_fail(raw_2627: RawSeason, small_cfg: dict) -> None:
    raw_2627.teams.loc[1, "code"] = raw_2627.teams.loc[0, "code"]
    assert "teams" in problems(raw_2627, small_cfg)


@pytest.mark.parametrize(
    ("key", "text"),
    [
        ("teams_rows", "teams"),
        ("players_rows_per_snapshot", "players"),
        ("playerstats_rows_snapshot", "playerstats"),
        ("player_gameweek_stats_rows_per_gw", "player_gameweek_stats"),
        ("playermatchstats_rows_per_match", "playermatchstats"),
        ("matches_rows", "matches"),
        ("prem_matches_rows", "prem"),
    ],
)
def test_row_counts_outside_the_bounds_fail(
    raw_2627: RawSeason, small_cfg: dict, key: str, text: str
) -> None:
    small_cfg["validation"][key] = [10_000, 20_000]
    assert text in problems(raw_2627, small_cfg)


def test_prices_outside_the_bounds_fail(raw_2627: RawSeason, small_cfg: dict) -> None:
    raw_2627.playerstats.loc[0, "now_cost"] = 158.0  # tenths by mistake
    assert "now_cost" in problems(raw_2627, small_cfg)


def test_no_played_gameweek_fails(raw_2627: RawSeason, small_cfg: dict) -> None:
    raw_2627.latest_gw = 0
    assert "latest gameweek" in problems(raw_2627, small_cfg)


def test_a_gap_before_the_latest_gameweek_fails(raw_2627: RawSeason, small_cfg: dict) -> None:
    raw_2627.gw_rows["player_gameweek_stats"][1] = 0
    assert "gap" in problems(raw_2627, small_cfg)


def test_player_stats_after_the_latest_gameweek_fail(
    raw_2627: RawSeason, small_cfg: dict
) -> None:
    raw_2627.gw_rows["playermatchstats"][3] = 40
    assert "after the latest" in problems(raw_2627, small_cfg)


def test_a_finished_match_after_the_latest_gameweek_fails(
    raw_2627: RawSeason, small_cfg: dict
) -> None:
    m = raw_2627.matches
    idx = m.index[m.snapshot_gw == 3][0]
    m.loc[idx, "finished"] = True
    assert "finished match" in problems(raw_2627, small_cfg)


def test_a_missing_gameweek_folder_fails(raw_2627: RawSeason, small_cfg: dict) -> None:
    raw_2627.matches = raw_2627.matches[raw_2627.matches.snapshot_gw != 3]
    assert "folder" in problems(raw_2627, small_cfg)


def test_stats_for_an_unknown_match_fail(raw_2627: RawSeason, small_cfg: dict) -> None:
    raw_2627.playermatchstats.loc[0, "match_id"] = "nowhere"
    assert "unknown match" in problems(raw_2627, small_cfg)


def test_a_premier_league_match_without_a_known_team_fails(
    raw_2627: RawSeason, small_cfg: dict
) -> None:
    m = raw_2627.matches
    m.loc[m.tournament == "prem", "home_team"] = 999.0
    assert "team" in problems(raw_2627, small_cfg)


def test_fixtures_and_matches_must_list_the_same_matches(
    raw_2627: RawSeason, small_cfg: dict
) -> None:
    raw_2627.fixture_ids = raw_2627.fixture_ids.iloc[1:]
    assert "fixtures.csv" in problems(raw_2627, small_cfg)


def test_a_match_gameweek_that_differs_from_its_folder_fails(
    raw_2627: RawSeason, small_cfg: dict
) -> None:
    raw_2627.matches.loc[0, "gameweek"] = 9.0
    assert "gameweek" in problems(raw_2627, small_cfg)


def test_a_premier_league_match_without_a_kickoff_time_fails(
    raw_2627: RawSeason, small_cfg: dict
) -> None:
    m = raw_2627.matches
    m.loc[m.index[m.tournament == "prem"][0], "kickoff_time"] = None
    assert "kickoff_time" in problems(raw_2627, small_cfg)


def test_a_cup_match_without_a_kickoff_time_is_allowed(
    raw_2627: RawSeason, small_cfg: dict
) -> None:
    m = raw_2627.matches
    m.loc[m.index[m.tournament != "prem"][0], "kickoff_time"] = None
    assert problems(raw_2627, small_cfg) == ""


def test_the_premier_league_tag_comes_from_config(raw_2627: RawSeason, small_cfg: dict) -> None:
    small_cfg["premier_league_tag"] = "nothing"
    assert "prem matches: 0 rows" in problems(raw_2627, small_cfg)


def test_a_small_shortfall_of_premier_league_matches_is_allowed_with_a_warning(
    raw_2627: RawSeason, small_cfg: dict, caplog: pytest.LogCaptureFixture
) -> None:
    n = int((raw_2627.matches.tournament == "prem").sum())
    small_cfg["validation"]["prem_matches_rows"] = [n - 1, n + 1]
    with caplog.at_level("WARNING"):
        assert problems(raw_2627, small_cfg) == ""
    assert any(f"{n} " in r.message and "postponed" in r.message for r in caplog.records)
    small_cfg["validation"]["prem_matches_rows"] = [n, n]
    caplog.clear()
    with caplog.at_level("WARNING"):
        assert problems(raw_2627, small_cfg) == ""
    assert not caplog.records


def test_validate_inputs_itself_enforces_the_rule_15_guards(
    raw_2627: RawSeason, small_cfg: dict
) -> None:
    raw_2627.playermatchstats["interceptions"] = np.nan
    assert "rule 15" in problems(raw_2627, small_cfg)


def test_validate_inputs_fails_on_a_blank_xg_beside_shots(
    raw_2627: RawSeason, small_cfg: dict
) -> None:
    pms, m = raw_2627.playermatchstats, raw_2627.matches
    idx = pms.index[pms.match_id.isin(m.match_id[m.finished])][0]
    pms.loc[idx, ["xg", "total_shots"]] = [np.nan, 3.0]
    assert "xg is blank" in problems(raw_2627, small_cfg)


def test_check_references_uses_the_configured_tag(raw_2627: RawSeason, small_cfg: dict) -> None:
    # The first cup match has no home club in teams.csv; with the cup as the tag that is a
    # problem, so a hardcoded "prem" in the check would not report it.
    small_cfg["premier_league_tag"] = "efl-cup"
    assert "efl-cup matches have a team code not in teams.csv" in problems(raw_2627, small_cfg)


def test_all_problems_are_reported_together(raw_2627: RawSeason, small_cfg: dict) -> None:
    raw_2627.missing_files = ["x.csv"]
    raw_2627.latest_gw = 0
    with pytest.raises(ValidationError) as exc:
        validate_inputs(raw_2627, small_cfg, season_cfg(small_cfg, raw_2627.season))
    assert len(exc.value.problems) >= 2
