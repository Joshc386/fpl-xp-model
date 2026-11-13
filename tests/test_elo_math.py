"""The Elo arithmetic, checked against hand-computed values."""

from __future__ import annotations

import pytest

from fpl.models.elo import EloSettings, elo_change, expected_home, margin_factor, model_config


def test_expected_home_score_with_home_advantage() -> None:
    # Gap 1600 + 50 - 1500 = 150: E = 1 / (1 + 10^(-150/400)) = 1 / 1.421697 = 0.703385.
    s = EloSettings(k=20.0, home_advantage=50.0, margin_power=0.5, scale=400.0)
    assert expected_home(1600.0, 1500.0, s) == pytest.approx(0.703385, abs=1e-6)


def test_equal_clubs_expect_one_half_without_home_advantage() -> None:
    s = EloSettings(k=20.0, home_advantage=0.0, margin_power=0.5, scale=400.0)
    assert expected_home(1700.0, 1700.0, s) == 0.5


@pytest.mark.parametrize(("diff", "power", "want"), [
    (0, 0.5, 1.0), (1, 0.5, 1.0), (-1, 0.5, 1.0), (3, 0.5, 3 ** 0.5), (-4, 0.25, 4 ** 0.25),
    (5, 0.0, 1.0),
])
def test_margin_factor_is_the_goal_difference_to_a_power_from_one_goal(
    diff: int, power: float, want: float
) -> None:
    assert margin_factor(diff, power) == pytest.approx(want)


def test_one_update_with_home_advantage_and_margin() -> None:
    # 3-0 home win, 1600 v 1500, HFA 50, K 20, power 0.5:
    # 20 x sqrt(3) x (1 - 0.703385) = 20 x 1.732051 x 0.296615 = 10.2750.
    s = EloSettings(k=20.0, home_advantage=50.0, margin_power=0.5, scale=400.0)
    assert elo_change(1600.0, 1500.0, 3, 0, s) == pytest.approx(10.275045, abs=1e-6)


def test_a_goalless_draw_between_equals_costs_the_home_club() -> None:
    # Gap 50: E = 1 / (1 + 10^(-0.125)) = 0.571463; 20 x (0.5 - 0.571463) = -1.42926.
    s = EloSettings(k=20.0, home_advantage=50.0, margin_power=0.5, scale=400.0)
    assert elo_change(1500.0, 1500.0, 0, 0, s) == pytest.approx(-1.429262, abs=1e-6)


def test_a_one_goal_away_win_is_not_scaled_by_the_margin() -> None:
    # 1-2, 1550 v 1450, no HFA, K 30: E = 1 / (1 + 10^(-0.25)) = 0.640065; 30 x -0.640065.
    s = EloSettings(k=30.0, home_advantage=0.0, margin_power=0.5, scale=400.0)
    assert elo_change(1550.0, 1450.0, 1, 2, s) == pytest.approx(-19.201950, abs=1e-6)


def test_settings_come_from_model_yaml() -> None:
    cfg = model_config()
    s = EloSettings.from_config(cfg)
    assert (s.k, s.home_advantage, s.margin_power, s.scale) == (
        cfg["elo"]["k"], cfg["elo"]["home_advantage"], cfg["elo"]["margin_power"],
        cfg["elo"]["scale"],
    )
    assert cfg["max_horizon"] == 5
