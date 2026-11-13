"""The Elo goals model: the Poisson fit, the fixture window and its point-in-time pool."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from elo_tables import CODES_A, FIXTURES_A, FIXTURES_B, PREM, SETTINGS, season_read, two_seasons
from fpl.models.elo import model_config, prem_fixtures, run_elo
from fpl.models.team_goals import (
    GoalsFit,
    GoalsModelError,
    GoalsSettings,
    InsufficientSampleError,
    clean_sheet_probability,
    fit_goals_model,
    fixture_difficulty,
    goals_from_history,
    goals_pool,
    poisson_fit,
)

GOALS = GoalsSettings(pool_seasons=2, min_matches=5, tol=1e-10, max_iter=50, max_horizon=2)
COLUMNS = ["team_id", "match_id", "gw", "opponent_id", "home", "lambda_for", "lambda_against",
           "p_cs"]
# Season A to as-of 3, then the schedule: club 1 has a double in GW4, club 4 a blank.
FUTURE = FIXTURES_A + [(gw, h, a, None, None, None, None) for gw, h, a in [
    (4, 1, 2), (4, 3, 1), (5, 4, 1), (5, 2, 3), (6, 1, 3), (6, 2, 4)]]


def test_poisson_fit_recovers_log_linear_cell_means() -> None:
    # Cell means 1, 2, 1.5, 3 at (gap, home) = (0,0), (100,0), (0,1), (100,1) are exactly
    # log-linear, so the MLE is log mu = 0 + gap x ln2/100 + home x ln1.5.
    cells = [((0, 0), [0, 1, 2]), ((100, 0), [1, 2, 3]), ((0, 1), [1, 2]), ((100, 1), [2, 3, 4])]
    x = np.array([[1.0, g, h] for (g, h), ys in cells for _ in ys])
    y = np.array([float(v) for _, ys in cells for v in ys])
    beta = poisson_fit(x, y, tol=1e-12, max_iter=50)
    assert beta == pytest.approx([0.0, 0.006931472, 0.405465108], abs=1e-8)


def test_poisson_fit_with_an_intercept_only_is_the_log_mean() -> None:
    beta = poisson_fit(np.ones((4, 1)), np.array([0.0, 1.0, 2.0, 5.0]), tol=1e-12, max_iter=50)
    assert beta == pytest.approx([math.log(2.0)])


@pytest.mark.parametrize(("x", "y", "match"), [
    (np.ones((3, 1)), np.zeros(3), "no goals"),
    (np.column_stack([np.ones(3), np.zeros(3)]), np.ones(3), "singular"),
])
def test_poisson_fit_raises_on_a_degenerate_pool(x: np.ndarray, y: np.ndarray, match: str) -> None:
    with pytest.raises(GoalsModelError, match=match):
        poisson_fit(x, y, tol=1e-12, max_iter=50)


def test_poisson_fit_raises_when_it_does_not_converge() -> None:
    x = np.column_stack([np.ones(4), [0.0, 1.0, 2.0, 3.0]])
    with pytest.raises(GoalsModelError, match="converge"):
        poisson_fit(x, np.array([1.0, 0.0, 3.0, 9.0]), tol=1e-12, max_iter=1)


def test_clean_sheet_probability_is_exp_of_minus_lambda_against() -> None:
    assert clean_sheet_probability(np.array([0.0, 1.2])) == pytest.approx([1.0, 0.301194212])


def test_the_mean_fitted_lambda_is_the_pool_mean_goals() -> None:
    run = run_elo(two_seasons(), SETTINGS, PREM)
    pool = goals_pool(run.matches, ["2025-2026", "2026-2027"])
    fit = fit_goals_model(pool, GOALS)
    assert len(pool) == 20 and fit.n_matches == 10
    assert fit.lam(pool.gap.to_numpy(), pool.home.to_numpy()).mean() == pytest.approx(
        pool.goals.mean())


def test_a_pool_below_the_minimum_raises_and_so_does_an_empty_one() -> None:
    run = run_elo(two_seasons(), SETTINGS, PREM)
    small = GoalsSettings(pool_seasons=2, min_matches=11, tol=1e-10, max_iter=50, max_horizon=2)
    with pytest.raises(InsufficientSampleError, match="10 finished matches"):
        fit_goals_model(goals_pool(run.matches, ["2025-2026", "2026-2027"]), small)
    with pytest.raises(InsufficientSampleError, match="0 finished matches"):
        fit_goals_model(goals_pool(run.matches, ["2099-2100"]), GOALS)


def pool_of(n_matches: int) -> pd.DataFrame:
    """A non-degenerate pool of `n_matches` matches (two team rows each)."""
    i = np.arange(n_matches)
    gap = (i % 7 - 3) * 40.0
    return pd.DataFrame({"goals": np.concatenate([i % 4, i % 3]).astype("float64"),
                         "gap": np.concatenate([gap, -gap]),
                         "home": np.concatenate([np.ones(n_matches), np.zeros(n_matches)])})


def test_the_configured_minimum_is_inclusive() -> None:
    s = GoalsSettings.from_config(model_config())
    assert s.min_matches == 30
    assert fit_goals_model(pool_of(30), s).n_matches == 30
    with pytest.raises(InsufficientSampleError, match="29 finished matches"):
        fit_goals_model(pool_of(29), s)


@pytest.mark.parametrize("pool_seasons", [0, -1])
def test_pool_seasons_below_one_is_rejected(pool_seasons: int) -> None:
    cfg = model_config()
    cfg["goals_model"]["pool_seasons"] = pool_seasons
    with pytest.raises(ValueError, match="pool_seasons must be at least 1"):
        GoalsSettings.from_config(cfg)


def test_the_pool_is_this_season_and_last_only() -> None:
    history = [season_read("2024-2025", 3, CODES_A, FIXTURES_A)] + two_seasons()
    _, fit = goals_from_history(history, SETTINGS, GOALS, PREM)
    assert fit.n_matches == 10  # season A (6) and B (4), not the season before


def test_rows_cover_the_horizon_with_doubles_and_blanks() -> None:
    out, _ = goals_from_history([season_read("2025-2026", 3, CODES_A, FUTURE)], SETTINGS, GOALS,
                                PREM)
    assert list(out.columns) == COLUMNS and len(out) == 8 and set(out.gw) == {4, 5}
    gw4 = out[out.gw == 4]
    assert (gw4.team_id == 1).sum() == 2 and 4 not in set(gw4.team_id)
    assert not out.duplicated(["team_id", "match_id"]).any() and not out.isna().any().any()
    assert str(out.home.dtype) == "bool" and str(out.team_id.dtype) == "int64"


def test_lambda_against_is_the_opponents_lambda_for_and_p_cs_follows() -> None:
    out, _ = goals_from_history([season_read("2025-2026", 3, CODES_A, FUTURE)], SETTINGS, GOALS,
                                PREM)
    mirror = out.set_index(["match_id", "team_id"]).lambda_for
    opp = out.set_index(["match_id", "opponent_id"]).lambda_for.rename_axis(["match_id", "team_id"])
    pd.testing.assert_series_equal(
        out.set_index(["match_id", "team_id"]).lambda_against, opp.reindex(mirror.index),
        check_names=False)
    assert out.p_cs.to_numpy() == pytest.approx(np.exp(-out.lambda_against.to_numpy()))


def test_the_horizon_stops_at_gameweek_38_and_skips_a_postponed_past_fixture() -> None:
    end = FIXTURES_A + [(36, 1, 2, None, None, None, None), (37, 3, 4, None, None, None, None),
                        (38, 2, 1, None, None, None, None)]
    five = GoalsSettings(pool_seasons=2, min_matches=5, tol=1e-10, max_iter=50, max_horizon=5)
    out, _ = goals_from_history([season_read("2025-2026", 36, CODES_A, end)], SETTINGS, five,
                                PREM)
    assert sorted(set(out.gw)) == [37, 38] and len(out) == 4  # GW36's unplayed fixture is past


def test_future_fixtures_use_each_clubs_current_rating() -> None:
    read = season_read("2025-2026", 3, CODES_A, FUTURE)
    run = run_elo([read], SETTINGS, PREM)
    fit = GoalsFit(intercept=0.1, gap=0.002, home=0.2, n_matches=10, mean_goals=1.3)
    out = fixture_difficulty(prem_fixtures(read, PREM), 3, 2, run.ratings, fit)
    row = out[(out.gw == 5) & (out.team_id == 4)].iloc[0]  # club 4 (code 34) at home to club 1
    gap = run.ratings[34] - run.ratings[31]
    assert row.lambda_for == pytest.approx(math.exp(0.1 + 0.002 * gap + 0.2))
    assert row.lambda_against == pytest.approx(math.exp(0.1 - 0.002 * gap))


def test_with_equal_ratings_the_home_side_expects_more_when_home_is_positive() -> None:
    read = season_read("2025-2026", 3, CODES_A, FUTURE)
    fit = GoalsFit(intercept=0.2, gap=0.003, home=0.15, n_matches=10, mean_goals=1.3)
    equal = dict.fromkeys(CODES_A.values(), 1500.0)
    home = fixture_difficulty(prem_fixtures(read, PREM), 3, 2, equal, fit).query("home")
    assert (home.lambda_for > home.lambda_against).all()


def test_a_club_without_a_rating_raises() -> None:
    read = season_read("2025-2026", 3, CODES_A, FUTURE)
    fit = GoalsFit(intercept=0.2, gap=0.003, home=0.15, n_matches=10, mean_goals=1.3)
    with pytest.raises(GoalsModelError, match="no rating"):
        fixture_difficulty(prem_fixtures(read, PREM), 3, 2, {31: 1500.0}, fit)


def test_adding_a_later_result_changes_nothing() -> None:
    # Season B at as-of 1 holds GW2 results in its table; schedule-only GW2 must give the same.
    schedule = [f if f[0] <= 1 else f[:3] + (None, None, None, None) for f in FIXTURES_B]
    one = GoalsSettings(pool_seasons=2, min_matches=5, tol=1e-10, max_iter=50, max_horizon=2)
    leaked, fit_l = goals_from_history(two_seasons(as_of_b=1), SETTINGS, one, PREM)
    clean, fit_c = goals_from_history(
        [two_seasons()[0], season_read("2026-2027", 1, two_seasons()[1].tables["dim_team"]
                                       .set_index("team_id").team_code.to_dict(), schedule)],
        SETTINGS, one, PREM)
    assert fit_l == fit_c
    pd.testing.assert_frame_equal(leaked, clean)
