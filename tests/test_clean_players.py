"""Cleaning rules for dim_player, fact_player_match and fact_player_gw."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fpl.clean import build_dim_player, build_fact_player_match
from fpl.frames import CleanError, JoinError
from fpl.schema import check_table_schema
from fpl.validate import ValidationError
from helpers import (
    FILL,
    POSITIONS,
    SWAPPED,
    blank_frame,
    match_row,
    matches_frame,
    player_row,
    players_frame,
    pm_inputs,
    pms_frame,
    pms_row,
)

# ---- dim_player -------------------------------------------------------------------------------

def playerstats_frame(rows: list[dict]) -> pd.DataFrame:
    base = {
        "status": "a", "news": None, "chance_of_playing_next_round": np.nan, "now_cost": 15.8,
        "selected_by_percent": 12.3, "penalties_order": np.nan, "direct_freekicks_order": 2.0,
        "corners_and_indirect_freekicks_order": np.nan, "ep_next": 4.5,
    }
    return blank_frame("playerstats", [{**base, **r} for r in rows])


def test_dim_player_maps_position_price_team_and_nullable_fields() -> None:
    players = players_frame([
        player_row(10, 3, position="Goalkeeper"), player_row(11, 7, position="Forward"),
    ])
    stats = playerstats_frame([
        {"id": 10, "now_cost": 4.5, "chance_of_playing_next_round": 75.0, "news": "Knock"},
        {"id": 11},
    ])
    out, dropped = build_dim_player(players, stats, SWAPPED, POSITIONS)
    assert out.position.tolist() == ["GKP", "FWD"]
    assert out.price_tenths.tolist() == [45, 158]  # 15.8 * 10 is 158.00000000000003
    assert out.team_id.tolist() == [1, 2]
    assert out.chance_next.tolist()[0] == 75 and pd.isna(out.chance_next.tolist()[1])
    assert out.pen_order.isna().all() and out.fk_order.tolist() == [2, 2]
    assert out.news.tolist()[0] == "Knock" and out.news.isna().tolist()[1]
    assert dropped == {"no_playerstats_row": 0}
    assert check_table_schema(out, "dim_player") == []


def test_dim_player_drops_and_counts_players_with_no_playerstats_row() -> None:
    players = players_frame([player_row(10, 3), player_row(11, 7)])
    out, dropped = build_dim_player(players, playerstats_frame([{"id": 10}]), SWAPPED, POSITIONS)
    assert out.player_id.tolist() == [10]
    assert dropped == {"no_playerstats_row": 1}


def test_dim_player_rejects_an_unknown_position() -> None:
    players = players_frame([player_row(10, 3, position="Manager")])
    with pytest.raises(CleanError, match="position"):
        build_dim_player(players, playerstats_frame([{"id": 10}]), SWAPPED, POSITIONS)


# ---- fact_player_match --------------------------------------------------------------------------

def run_pm(pms: pd.DataFrame, matches: pd.DataFrame, players: pd.DataFrame,
           tackles: str = "tackles") -> tuple[pd.DataFrame, dict[str, int]]:
    return build_fact_player_match(pms, matches, players, SWAPPED, tackles, FILL)


def test_minutes_come_from_minutes_played_and_team_from_that_gameweeks_snapshot() -> None:
    matches, players = pm_inputs()
    pms = pms_frame([
        pms_row(10, "m1", 90.0), pms_row(10, "m2", 45.0, snapshot_gw=2),
    ])
    out, dropped = run_pm(pms, matches, players)
    assert out.minutes.tolist() == [90, 45]
    # Player 10 moved from code 3 (id 1) to code 7 (id 2) between the two snapshots.
    assert out.team_id.tolist() == [1, 2]
    assert sum(dropped.values()) == 0
    assert check_table_schema(out, "fact_player_match") == []


def test_rows_of_unprocessed_matches_are_dropped_by_reason() -> None:
    matches = matches_frame([
        match_row("ok", 3.0, 7.0),
        match_row("live", 3.0, 7.0, finished=False),
        match_row("stats", 3.0, 7.0, player_stats_processed=False),
        match_row("nokick", 3.0, 7.0, kickoff_time=None),
    ])
    players = players_frame([player_row(10, 3)])
    pms = pms_frame([pms_row(10, m, 90.0) for m in ("ok", "live", "stats", "nokick")])
    out, dropped = run_pm(pms, matches, players)
    assert out.match_id.tolist() == ["ok"]
    assert dropped == {
        "match_has_no_kickoff_time": 1, "match_not_processed": 2, "player_not_in_snapshot": 0,
    }


def test_a_player_missing_from_the_gameweek_snapshot_is_dropped_and_counted() -> None:
    matches, players = pm_inputs()
    pms = pms_frame([pms_row(10, "m1", 90.0), pms_row(99, "m1", 0.0)])
    out, dropped = run_pm(pms, matches, players)
    assert out.player_id.tolist() == [10]
    assert dropped["player_not_in_snapshot"] == 1


def test_a_row_for_an_unknown_match_is_an_error_not_a_silent_drop() -> None:
    matches, players = pm_inputs()
    pms = pms_frame([pms_row(10, "nowhere", 90.0)])
    with pytest.raises(JoinError, match="match"):
        run_pm(pms, matches, players)


def test_blanks_are_filled_with_zero_including_zero_minute_rows() -> None:
    matches, players = pm_inputs()
    blank = dict.fromkeys(
        ["goals", "assists", "xg", "xa", "total_shots", "tackles", "tackles_won",
         "interceptions", "clearances", "blocks", "recoveries", "saves",
         "penalties_scored", "penalties_missed"],
        np.nan,
    )
    pms = pms_frame([
        pms_row(10, "m1", 90.0),
        pms_row(11, "m1", 0.0, **blank),
        pms_row(10, "m2", 30.0, snapshot_gw=2, xg=np.nan, total_shots=0.0, saves=np.nan),
    ])
    out, _ = run_pm(pms, matches, players)
    zero_min = out[out.minutes == 0].iloc[0]
    assert zero_min[FILL].tolist() == [0] * len(FILL)
    assert out.loc[out.minutes == 30, ["xg", "saves"]].iloc[0].tolist() == [0.0, 0]
    assert out[FILL].isna().sum().sum() == 0


def test_team_goals_conceded_is_not_carried() -> None:
    matches, players = pm_inputs()
    out, _ = run_pm(pms_frame([pms_row(10, "m1", 60.0)]), matches, players)
    assert "team_gc_on_pitch" not in out.columns


def test_tackles_come_from_the_configured_source_column() -> None:
    matches, players = pm_inputs()
    pms = pms_frame([pms_row(10, "m1", 90.0, tackles=np.nan, tackles_won=4.0)])
    out, _ = run_pm(pms, matches, players, tackles="tackles_won")
    assert out.tackles.tolist() == [4]
    pms = pms_frame([pms_row(10, "m1", 90.0, tackles=5.0, tackles_won=np.nan)])
    out, _ = run_pm(pms, matches, players, tackles="tackles")
    assert out.tackles.tolist() == [5]


def test_a_column_empty_for_the_whole_season_is_not_filled_it_fails() -> None:
    matches, players = pm_inputs()
    pms = pms_frame([pms_row(10, "m1", 90.0, tackles=np.nan, tackles_won=3.0)])
    # Mapping to the wrong (all-blank) source column must fail rather than fill zeros.
    with pytest.raises(ValidationError, match="tackles"):
        run_pm(pms, matches, players, tackles="tackles")


def test_a_blank_xg_beside_shots_fails() -> None:
    matches, players = pm_inputs()
    pms = pms_frame([pms_row(10, "m1", 90.0), pms_row(11, "m1", 90.0, xg=np.nan, total_shots=2.0)])
    with pytest.raises(ValidationError, match="xg"):
        run_pm(pms, matches, players)


def test_non_integer_counts_are_an_error() -> None:
    matches, players = pm_inputs()
    pms = pms_frame([pms_row(10, "m1", 90.0, goals=0.5)])
    with pytest.raises(CleanError, match="goals"):
        run_pm(pms, matches, players)


def test_a_player_whose_club_is_not_in_teams_is_an_error() -> None:
    players = players_frame([player_row(10, 99)])
    with pytest.raises(CleanError, match="team"):
        build_dim_player(players, playerstats_frame([{"id": 10}]), SWAPPED, POSITIONS)
    matches, _ = pm_inputs()
    with pytest.raises(CleanError, match="team"):
        run_pm(pms_frame([pms_row(10, "m1", 90.0)]), matches, players)
