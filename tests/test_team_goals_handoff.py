"""Team goals v1's hand-off (`team_goals`): the Elo goals model's rows plus `lambda_pen`.

Known output, checked by hand (2026-11-25) on season A in full and season B at as-of 2 with
`PENS_A` and `PENS_B` (tests/penalty_tables.py), k = 5: 20 team-matches hold 3.15 penalty
xG, a league mean of 0.1575, so 5 x mean = 0.7875. In season B's GW3 horizon:
* id 1 (code 33): A 3 matches 0, B 2 matches 0.79: (0.79 + 0.7875) / 10 = 0.15775;
* id 4 (code 32): A 0.79 in 3, B 0 in 2: 0.15775;
* id 3 (code 31): A 1.57 in 3, B 0 in 2: (1.57 + 0.7875) / 10 = 0.23575;
* id 2 (code 35, promoted): B 0 in 2: 0.7875 / 7 = 0.1125.
The Elo goals columns are tests/test_elo_regression.py's, unchanged.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import pytest

import fpl.models.team_goals as team_goals_module
import synth
from elo_tables import CODES_A, CODES_B, FIXTURES_A, FIXTURES_B, PREM, SETTINGS, season_read
from fpl.models import elo
from fpl.models.elo import MissingSeedError, model_config
from fpl.models.team_goals import (
    OUT_COLUMNS,
    TEAM_GOALS_COLUMNS,
    GoalsSettings,
    InsufficientSampleError,
    elo_goals,
    goals_from_history,
    team_goals,
    team_goals_from_history,
)
from penalty_tables import PENS_A, PENS_B, complete

# Season A to as-of 3, then the schedule: club 1 has a double in GW4 (home, then away).
FUTURE = FIXTURES_A + [(gw, h, a, None, None, None, None) for gw, h, a in [
    (4, 1, 2), (4, 3, 1), (5, 4, 1), (5, 2, 3), (6, 1, 3), (6, 2, 4)]]
GOALS = GoalsSettings(pool_seasons=2, min_matches=5, tol=1e-10, max_iter=50, max_horizon=2,
                      prior_sd_gap=0.00175, prior_sd_home=0.175)
K = 5.0


def history(as_of_b: int = 2, pens_b: dict | None = PENS_B) -> list:
    """Season A in full and season B at `as_of_b`, both complete, with known penalties."""
    return [complete(season_read("2025-2026", 3, CODES_A, FIXTURES_A), PENS_A),
            complete(season_read("2026-2027", as_of_b, CODES_B, FIXTURES_B), pens_b)]


def test_the_columns_are_the_elo_goals_columns_plus_two() -> None:
    assert TEAM_GOALS_COLUMNS == ["team_id", "match_id", "gw", "opponent_id", "home",
                                  "lambda_for", "lambda_against", "lambda_pen",
                                  "lambda_league", "p_cs"]
    assert set(TEAM_GOALS_COLUMNS) - set(OUT_COLUMNS) == {"lambda_pen", "lambda_league"}


def test_known_output() -> None:
    out = team_goals_from_history(history(), SETTINGS, GOALS, K, PREM)
    assert list(out.columns) == TEAM_GOALS_COLUMNS
    assert out.team_id.tolist() == [1, 4, 3, 2]
    assert out.lambda_pen.tolist() == pytest.approx([0.15775, 0.15775, 0.23575, 0.1125],
                                                    abs=1e-9)
    assert out.lambda_for.tolist() == pytest.approx([1.364660, 1.226593, 1.485900, 1.126510],
                                                    abs=1e-6)
    assert out.lambda_league.tolist() == pytest.approx([1.3] * 4)  # the pool's mean goals
    assert str(out.lambda_pen.dtype) == "float64" and not out.isna().any().any()


def test_the_elo_goals_rows_are_unchanged() -> None:
    out = team_goals_from_history(history(), SETTINGS, GOALS, K, PREM)
    goals, fit = goals_from_history(history(), SETTINGS, GOALS, PREM)
    pd.testing.assert_frame_equal(out[OUT_COLUMNS], goals)
    assert (out.lambda_league == fit.mean_goals).all()


def test_a_club_with_no_complete_match_in_the_pool_gets_the_league_mean() -> None:
    reads = history()
    reads[1] = season_read("2026-2027", 2, CODES_B, FIXTURES_B)  # B finished, no xG yet
    out = team_goals_from_history(reads, SETTINGS, GOALS, K, PREM)
    mean = 2.36 / 12
    promoted = out.set_index("team_id").lambda_pen[2]  # code 35: no season A match
    assert promoted == pytest.approx(mean)
    assert out.set_index("team_id").lambda_pen[3] == pytest.approx((1.57 + K * mean) / (3 + K))


def test_the_pool_is_this_season_and_last_only() -> None:
    older = complete(season_read("2024-2025", 3, CODES_A, FIXTURES_A),
                     {(i, side): 0.79 for i in range(6) for side in ("home", "away")})
    three = team_goals_from_history([older, *history()], SETTINGS, GOALS, K, PREM)
    two = team_goals_from_history(history(), SETTINGS, GOALS, K, PREM)
    assert three.lambda_pen.tolist() == pytest.approx(two.lambda_pen.tolist())


def test_a_club_has_one_rate_at_home_away_and_in_both_fixtures_of_a_double() -> None:
    read = complete(season_read("2025-2026", 3, CODES_A, FUTURE), PENS_A)
    out = team_goals_from_history([read], SETTINGS, GOALS, 3.0, PREM)
    club1 = out[out.team_id == 1]
    assert len(club1[club1.gw == 4]) == 2 and set(club1.home) == {True, False}
    assert club1.lambda_pen.tolist() == pytest.approx([0.36] * len(club1))


def test_adding_a_later_result_with_xg_changes_nothing() -> None:
    # Season B at as-of 1 with GW2 complete in its table, against GW2 as schedule only.
    leaked = history(as_of_b=1, pens_b={(2, "home"): 0.79, (3, "away"): 0.78})
    schedule = [f if f[0] <= 1 else f[:3] + (None,) * 4 for f in FIXTURES_B]
    clean = [leaked[0], complete(season_read("2026-2027", 1, CODES_B, schedule))]
    pd.testing.assert_frame_equal(
        team_goals_from_history(leaked, SETTINGS, GOALS, K, PREM),
        team_goals_from_history(clean, SETTINGS, GOALS, K, PREM))


@pytest.fixture
def on_synth(monkeypatch: pytest.MonkeyPatch,
             synth_load: Callable[[int, str], dict]) -> list[tuple]:
    """Point the Elo component's loader at the synthetic season; returns the calls made."""
    calls: list[tuple] = []

    def load(season: str, as_of: int, mode: str) -> dict:
        calls.append((season, as_of, mode))
        return synth_load(as_of, mode)

    monkeypatch.setattr(elo, "load_as_of", load)
    return calls


def test_the_public_function_reads_its_own_arguments(on_synth: list[tuple]) -> None:
    team_goals(synth.SEASON, 20, "live")
    assert on_synth == [(synth.SEASON, 20, "live")]


def test_the_public_function_adds_lambda_pen_to_the_elo_goals_rows(on_synth: list) -> None:
    out = team_goals(synth.SEASON, 20, "backtest")
    pd.testing.assert_frame_equal(out[OUT_COLUMNS], elo_goals(synth.SEASON, 20, "backtest"))
    assert sorted(set(out.gw)) == [21, 22, 23, 24, 25] and len(out) == 20
    # Every synthetic club-match has team xG 0.1 above its npxG, so every rate is 0.1.
    assert out.lambda_pen.to_numpy() == pytest.approx([0.1] * 20)
    assert not out.duplicated(["team_id", "match_id"]).any() and not out.isna().any().any()


@pytest.mark.parametrize(("as_of", "error"), [(0, MissingSeedError),
                                              (14, InsufficientSampleError)])
def test_the_public_function_raises_where_elo_goals_does(on_synth: list, as_of: int,
                                                         error: type[Exception]) -> None:
    with pytest.raises(error):
        elo_goals(synth.SEASON, as_of, "backtest")
    with pytest.raises(error):
        team_goals(synth.SEASON, as_of, "backtest")


def test_after_the_last_gameweek_the_output_is_empty_with_its_columns_typed(
        on_synth: list) -> None:
    out = team_goals(synth.SEASON, 38, "backtest")
    assert out.empty and list(out.columns) == TEAM_GOALS_COLUMNS
    types = dict.fromkeys(["lambda_for", "lambda_against", "lambda_pen", "lambda_league", "p_cs"],
                          "float64")
    expected = {"team_id": "int64", "match_id": "str", "gw": "int64", "opponent_id": "int64",
                "home": "bool"} | types
    assert out.dtypes.astype(str).to_dict() == expected
    full = team_goals(synth.SEASON, 20, "backtest")
    pd.testing.assert_series_equal(out.dtypes, full.dtypes)


def on_tables(monkeypatch: pytest.MonkeyPatch, k: float, pool_seasons: int = 2) -> None:
    """Point `team_goals` at `history()` and at the real config with `k` and `pool_seasons`.

    `goals_model.min_matches` drops to 4, so season B alone (4 matches) can be fitted.
    """
    cfg = model_config()
    cfg["goals_model"] |= {"min_matches": 4, "pool_seasons": pool_seasons}
    cfg["team_goals"]["penalty_prior_matches"] = k
    monkeypatch.setattr(team_goals_module, "model_config", lambda: cfg)
    monkeypatch.setattr(team_goals_module, "load_history", lambda *args: history())


@pytest.mark.parametrize("k", [3.0, 5.0])
def test_the_public_function_uses_the_configured_prior_strength(
        monkeypatch: pytest.MonkeyPatch, k: float) -> None:
    on_tables(monkeypatch, k)
    out = team_goals("2026-2027", 2, "backtest")
    mean = 3.15 / 20  # both seasons (module docstring); clubs in row order 1, 4, 3, 2
    expected = [(0.79 + k * mean) / (5 + k), (0.79 + k * mean) / (5 + k),
                (1.57 + k * mean) / (5 + k), k * mean / (2 + k)]
    assert out.team_id.tolist() == [1, 4, 3, 2]
    assert out.lambda_pen.tolist() == pytest.approx(expected, abs=1e-12)


def test_the_public_function_pools_the_configured_seasons(
        monkeypatch: pytest.MonkeyPatch) -> None:
    on_tables(monkeypatch, K, pool_seasons=1)
    out = team_goals("2026-2027", 2, "backtest")
    mean = 0.79 / 8  # season B alone: 8 team-matches, 2 a club; id 1 (code 33) has the 0.79
    expected = [(0.79 + K * mean) / (2 + K)] + [K * mean / (2 + K)] * 3
    assert out.lambda_pen.tolist() == pytest.approx(expected, abs=1e-12)
