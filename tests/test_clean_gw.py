"""Cleaning rules for fact_player_gw: FPL's figures and the finished-fixtures gate."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fpl.clean import build_fact_player_gw
from fpl.frames import CleanError
from fpl.schema import check_table_schema
from helpers import (
    blank_frame,
    match_row,
    matches_frame,
    player_row,
    players_frame,
    pm_inputs,
    teams_frame,
)


def pgs_frame(rows: list[dict]) -> pd.DataFrame:
    base = {
        "id": 10, "gw": 1, "event_points": 6.0, "minutes": 90.0, "starts": 1.0,
        "bonus": 2.0, "bps": 30.0, "yellow_cards": 1.0, "red_cards": 0.0, "own_goals": 0.0,
        "goals_conceded": 2.0, "tackles": 3.0, "clearances_blocks_interceptions": 5.0,
        "recoveries": 7.0, "defensive_contribution": 10.0, "now_cost": 15.8,
        "selected_by_percent": 12.5, "transfers_in_event": 100.0, "transfers_out_event": 50.0,
    }
    full = [{**base, **r} for r in rows]
    df = blank_frame("player_gameweek_stats", full)
    df["snapshot_gw"] = [r["gw"] for r in full]
    return df


# id != code for every club, so a join on the wrong key shows up in team_id.
TEAMS = teams_frame([(1, 3), (3, 1), (2, 7), (7, 2), (9, 5)])


def run_gw(
    pgs: pd.DataFrame, matches: pd.DataFrame, players: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, int]]:
    return build_fact_player_gw(pgs, players, matches, TEAMS, "2026-2027", "prem")


def test_fact_player_gw_maps_columns_and_uses_fpl_minutes() -> None:
    matches, players = pm_inputs()
    pgs = pgs_frame([{}, {"id": 11, "event_points": 0.0, "minutes": 0.0}])
    out, dropped = run_gw(pgs, matches, players)
    row = out.iloc[0]
    assert (row.points, row.minutes, row.starts, row.yellow, row.red) == (6, 90, 1, 1, 0)
    assert (row.goals_conceded, row.cbi, row.recoveries) == (2, 5, 7)
    assert row.defensive_contribution == 10
    assert (row.price_tenths, row.selected_pct) == (158, 12.5)
    assert (row.transfers_in, row.transfers_out, row.season, row.gw) == (100, 50, "2026-2027", 1)
    assert len(out) == 2 and sum(dropped.values()) == 0
    assert check_table_schema(out, "fact_player_gw") == []


def test_fact_player_gw_rejects_non_integer_minutes_and_null_goals_conceded() -> None:
    matches, players = pm_inputs()
    with pytest.raises(CleanError, match="minutes"):
        run_gw(pgs_frame([{"minutes": 59.5}]), matches, players)
    with pytest.raises(CleanError, match="goals_conceded"):
        run_gw(pgs_frame([{"goals_conceded": np.nan}]), matches, players)


UNPLAYED = {"finished": False}


def gate_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    """GW1: club code 3 has played, 7 has not; code 1 has a double with one played."""
    matches = matches_frame([
        match_row("played", 3.0, 99.0),
        match_row("future", 7.0, 98.0, **UNPLAYED),
        match_row("dgw_a", 1.0, 97.0),
        match_row("dgw_b", 96.0, 1.0, **UNPLAYED),
        match_row("cup", 5.0, 95.0, tournament="efl-cup", finished=False),
    ])
    players = players_frame([
        player_row(10, 3), player_row(11, 7), player_row(12, 1), player_row(13, 5),
        player_row(14, 2),
    ])
    return matches, players


def test_a_part_played_gameweek_drops_rows_of_clubs_that_have_not_played() -> None:
    matches, players = gate_inputs()
    out, dropped = run_gw(pgs_frame([{"id": 10}, {"id": 11}]), matches, players)
    assert out.player_id.tolist() == [10]
    assert dropped["club_fixture_not_finished"] == 1


def test_a_double_gameweek_with_one_fixture_finished_is_dropped() -> None:
    matches, players = gate_inputs()
    out, dropped = run_gw(pgs_frame([{"id": 12}]), matches, players)
    assert out.empty and dropped["club_fixture_not_finished"] == 1
    matches.loc[matches.match_id == "dgw_b", "finished"] = True
    out, _ = run_gw(pgs_frame([{"id": 12}]), matches, players)
    assert out.player_id.tolist() == [12]


def test_a_blank_gameweek_keeps_its_rows() -> None:
    matches, players = gate_inputs()
    out, dropped = run_gw(pgs_frame([{"id": 14}]), matches, players)  # club 2 has no fixture
    assert out.player_id.tolist() == [14] and dropped["club_fixture_not_finished"] == 0


def test_an_incomplete_but_finished_fixture_does_not_hold_rows_back() -> None:
    matches, players = gate_inputs()
    matches.loc[matches.match_id == "played", "home_expected_goals_xg"] = np.nan
    out, _ = run_gw(pgs_frame([{"id": 10}]), matches, players)
    assert out.player_id.tolist() == [10]


def test_only_premier_league_fixtures_gate_a_club() -> None:
    matches, players = gate_inputs()  # club 5 has an unfinished cup match only
    out, _ = run_gw(pgs_frame([{"id": 13}]), matches, players)
    assert out.player_id.tolist() == [13]


def test_the_gate_uses_the_club_in_that_gameweeks_snapshot() -> None:
    matches, _ = gate_inputs()
    players = players_frame([
        player_row(10, 7, snapshot_gw=1), player_row(10, 3, snapshot_gw=2),
    ])
    out, dropped = run_gw(pgs_frame([{"id": 10, "gw": 1}]), matches, players)
    assert out.empty and dropped["club_fixture_not_finished"] == 1


def test_a_player_missing_from_the_snapshot_is_held_while_the_gameweek_is_part_played() -> None:
    matches, players = gate_inputs()  # GW1 still has unfinished Premier League fixtures
    out, dropped = run_gw(pgs_frame([{"id": 77}, {"id": 10}]), matches, players)
    assert out.player_id.tolist() == [10]
    assert dropped == {"club_fixture_not_finished": 0, "no_club_gameweek_not_finished": 1}


def test_a_player_missing_from_the_snapshot_is_kept_once_the_gameweek_is_finished() -> None:
    matches, players = gate_inputs()
    matches["finished"] = True  # cup fixtures never count
    out, dropped = run_gw(pgs_frame([{"id": 77}]), matches, players)
    assert out.player_id.tolist() == [77]
    assert sum(dropped.values()) == 0


def test_a_missing_player_is_gated_by_its_own_gameweek() -> None:
    matches, players = gate_inputs()
    matches["finished"] = True
    later = matches.match_id == "future"
    matches.loc[later, ["gameweek", "snapshot_gw", "finished"]] = [2, 2, False]
    out, _ = run_gw(pgs_frame([{"id": 77, "gw": 1}, {"id": 77, "gw": 2}]), matches, players)
    assert out.gw.tolist() == [1]


def test_team_id_is_the_club_in_that_gameweeks_snapshot_mapped_through_the_code() -> None:
    matches, _ = gate_inputs()
    matches["finished"] = True
    players = players_frame([
        player_row(10, 3, snapshot_gw=1), player_row(10, 7, snapshot_gw=2),  # moves clubs
        player_row(11, 7, snapshot_gw=1), player_row(11, 7, snapshot_gw=2),
    ])
    pgs = pgs_frame([{"id": 10, "gw": 1}, {"id": 10, "gw": 2}, {"id": 11, "gw": 1}])
    out, _ = run_gw(pgs, matches, players)
    assert out.set_index(["player_id", "gw"]).team_id.to_dict() == {
        (10, 1): 1, (10, 2): 2, (11, 1): 2,  # code 3 is team 1, code 7 is team 2
    }
    assert check_table_schema(out, "fact_player_gw") == []


def test_team_id_is_null_for_a_player_missing_from_the_snapshot() -> None:
    matches, players = gate_inputs()
    matches["finished"] = True
    out, _ = run_gw(pgs_frame([{"id": 77}, {"id": 10}]), matches, players)
    assert out.set_index("player_id").team_id.isna().to_dict() == {77: True, 10: False}
    assert out.team_id.dtype == "Int64"


def test_a_club_code_not_in_teams_is_an_error() -> None:
    matches, players = gate_inputs()
    players.loc[players.player_id == 10, "team_code"] = 424.0
    with pytest.raises(CleanError, match="team_code"):
        run_gw(pgs_frame([{"id": 10}]), matches, players)
