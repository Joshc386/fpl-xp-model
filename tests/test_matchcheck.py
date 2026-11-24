"""The checks of fact_shot against matches.csv (pipeline build only): each fails when planted."""

from __future__ import annotations

import pandas as pd
import pytest

from fpl.matchcheck import check_against_matches
from shot_tables import mini, raw_matches


def run(t: dict, cfg: dict, matches: pd.DataFrame | None = None) -> tuple[list[str], dict]:
    return check_against_matches(t, raw_matches() if matches is None else matches, cfg)


def test_the_consistent_league_passes_with_every_count_zero(cfg: dict) -> None:
    problems, counts = run(mini(), cfg)
    assert problems == []
    assert counts == {
        "penalty_xg_mismatch": 0, "shot_count_mismatch": 0, "goals_mismatch": 0,
        "team_xg_mismatch": 0, "sides": 4, "team_xg_ratio": pytest.approx(1.0),
        "team_xg_mean_abs": pytest.approx(0.0, abs=1e-9),
    }


def test_penalty_xg_that_differs_from_team_xg_minus_npxg_fails(cfg: dict) -> None:
    t = mini()
    t["fact_fixture"].loc[0, "home_npxg"] = 0.2  # team penalty xG becomes 0.6884
    problems, counts = run(t, cfg)
    assert counts["penalty_xg_mismatch"] == 1 and any("penalty_xg_mismatch" in p for p in problems)


def test_a_penalty_shot_in_the_tolerance_passes(cfg: dict) -> None:
    t = mini()
    t["fact_fixture"].loc[0, "home_npxg"] = 0.1 + 0.01
    assert run(t, cfg)[1]["penalty_xg_mismatch"] == 0


def test_a_missing_penalty_shot_fails(cfg: dict) -> None:
    t = mini()
    shot = t["fact_shot"]
    t["fact_shot"] = shot[~(shot.is_penalty & (shot.match_id == "m1") & (shot.team_id == 1))]
    assert run(t, cfg)[1]["penalty_xg_mismatch"] == 1


def test_shot_counts_are_checked_against_total_shots(cfg: dict) -> None:
    m = raw_matches()
    m.loc[0, "home_total_shots"] = 5.0  # three more than the shot rows: at the tolerance of 3
    assert run(mini(), cfg, m)[1]["shot_count_mismatch"] == 0
    m.loc[0, "home_total_shots"] = 6.0
    problems, counts = run(mini(), cfg, m)
    assert counts["shot_count_mismatch"] == 1 and any("shot_count_mismatch" in p for p in problems)


def test_a_null_total_shots_is_a_mismatch(cfg: dict) -> None:
    m = raw_matches()
    m.loc[1, "away_total_shots"] = float("nan")
    assert run(mini(), cfg, m)[1]["shot_count_mismatch"] == 1


def test_goal_shots_must_equal_the_score_less_the_opponents_own_goals(cfg: dict) -> None:
    t = mini()
    t["fact_fixture"].loc[0, "home_goals"] = 2  # one goal more than the shots show
    problems, counts = run(t, cfg)
    assert counts["goals_mismatch"] == 1 and any("goals_mismatch" in p for p in problems)
    gw = t["fact_player_gw"]
    gw.loc[(gw.player_id == 201) & (gw.gw == 1), "own_goals"] = 1  # club 2 scored it for club 1
    assert run(t, cfg)[1]["goals_mismatch"] == 0


def test_more_goal_shots_than_goals_fails_even_with_own_goals(cfg: dict) -> None:
    t = mini()
    t["fact_fixture"].loc[0, "home_goals"] = 0
    gw = t["fact_player_gw"]
    gw.loc[(gw.player_id == 201) & (gw.gw == 1), "own_goals"] = 1
    assert run(t, cfg)[1]["goals_mismatch"] == 1


def test_an_own_goal_outcome_shot_counts_as_a_goal(cfg: dict) -> None:
    t = mini()
    shot = t["fact_shot"]
    shot.loc[(shot.match_id == "m1") & (shot.team_id == 1) & shot.is_penalty, "outcome"] = "ownGoal"
    assert run(t, cfg)[1]["goals_mismatch"] == 0


def test_team_xg_beyond_the_per_side_tolerance_fails(cfg: dict) -> None:
    t = mini()
    t["fact_fixture"].loc[0, "home_xg"] = 0.8884 + 1.3
    t["fact_fixture"].loc[0, "home_npxg"] = 0.1 + 1.3
    problems, counts = run(t, cfg)
    assert counts["team_xg_mismatch"] == 1 and any("team_xg_mismatch" in p for p in problems)


def test_the_season_ratio_and_mean_difference_are_checked(cfg: dict) -> None:
    t = mini()
    fx = t["fact_fixture"]
    fx["home_xg"] = fx.home_xg * 0.9
    fx["away_xg"] = fx.away_xg * 0.9
    fx["home_npxg"] = fx.home_npxg + (fx.home_xg - fx.home_npxg - 0.7884)  # keep penalty xG
    fx["away_npxg"] = fx.away_npxg + (fx.away_xg - fx.away_npxg - 0.7884)
    problems, counts = run(t, cfg)
    assert counts["team_xg_ratio"] == pytest.approx(1 / 0.9)
    assert any("ratio" in p for p in problems)


def test_the_mean_absolute_difference_has_its_own_limit(cfg: dict) -> None:
    t = mini()
    fx = t["fact_fixture"]
    for col in ("home_xg", "away_xg"):  # +0.3 and -0.3: no ratio change, each side inside 1.25
        fx[col] = fx[col] + [0.3, -0.3]
    for col in ("home_npxg", "away_npxg"):
        fx[col] = fx[col] + [0.3, -0.3]
    problems, counts = run(t, cfg)
    assert counts["team_xg_mean_abs"] == pytest.approx(0.3)
    assert any("mean" in p for p in problems)


def test_a_season_with_no_complete_match_passes(cfg: dict) -> None:
    t = {k: v.iloc[0:0] for k, v in mini().items()}
    assert run(t, cfg)[0] == []
