"""The outside-source Elo check's ordered logistic fit, on small inputs with known answers."""

from __future__ import annotations

import math

import numpy as np
import pytest
from backtest import beyondelo_fit as bf
from backtest.beyondelo_fit import AWAY, DRAW, HOME, FitError, fit_ordered, match_nll

TOL, MAX_IT, HALVINGS = 1e-12, 50, 60


def logit(p: float) -> float:
    return math.log(p / (1 - p))


def test_the_baseline_fit_predicts_the_leagues_home_draw_and_away_rates() -> None:
    y = np.array([AWAY] * 30 + [DRAW] * 20 + [HOME] * 50)
    f = fit_ordered(None, y, TOL, MAX_IT, HALVINGS)
    assert f.slope == 0.0 and f.n == 100
    assert f.cut_away_draw == pytest.approx(logit(0.3), abs=1e-10)
    assert f.cut_draw_home == pytest.approx(logit(0.5), abs=1e-10)
    nll = match_nll(f, None, y)
    want = -(30 * math.log(0.3) + 20 * math.log(0.2) + 50 * math.log(0.5)) / 100
    assert nll.mean() == pytest.approx(want, abs=1e-12)


def simulate(n: int, seed: int, slope: float = 0.006, cuts: tuple[float, float] = (-0.9, 0.3),
             sd: float = 150.0) -> tuple[np.ndarray, np.ndarray]:
    """Gaps and outcomes drawn from an ordered logistic model with known parameters."""
    rng = np.random.default_rng(seed)
    gap = rng.normal(0.0, sd, n)
    u = rng.uniform(size=n)
    p_away = 1 / (1 + np.exp(-(cuts[0] - slope * gap)))
    p_not_home = 1 / (1 + np.exp(-(cuts[1] - slope * gap)))
    return gap, np.where(u < p_away, AWAY, np.where(u < p_not_home, DRAW, HOME))


def total_loglik(params: tuple[float, float, float], gap: np.ndarray, y: np.ndarray) -> float:
    """The log-likelihood written out case by case, independently of the module."""
    c1, c2, b = params
    out = 0.0
    for g, k in zip(gap, y, strict=True):
        a = 1 / (1 + math.exp(-(c1 - b * g)))
        ad = 1 / (1 + math.exp(-(c2 - b * g)))
        out += math.log([a, ad - a, 1 - ad][k])
    return out


def test_the_gap_fit_is_a_maximum_of_the_likelihood() -> None:
    gap, y = simulate(300, 1)
    f = fit_ordered(gap, y, TOL, MAX_IT, HALVINGS)
    best = (f.cut_away_draw, f.cut_draw_home, f.slope)
    ll = total_loglik(best, gap, y)
    assert ll == pytest.approx(f.loglik, abs=1e-9)
    assert ll == pytest.approx(-match_nll(f, gap, y).sum(), abs=1e-9)
    for i, h in ((0, 1e-3), (1, 1e-3), (2, 1e-5)):
        for sign in (1, -1):
            moved = list(best)
            moved[i] += sign * h
            assert total_loglik(tuple(moved), gap, y) < ll


def test_a_large_sample_recovers_the_true_parameters() -> None:
    gap, y = simulate(20000, 2)
    f = fit_ordered(gap, y, TOL, MAX_IT, HALVINGS)
    assert f.slope == pytest.approx(0.006, rel=0.05)
    assert f.cut_away_draw == pytest.approx(-0.9, abs=0.05)
    assert f.cut_draw_home == pytest.approx(0.3, abs=0.05)


def test_an_affine_transform_of_the_ratings_gives_the_same_fit_and_log_losses() -> None:
    # Ratings a*r + b give gaps a*gap: the offset cancels in home minus away.
    gap, y = simulate(300, 3)
    f = fit_ordered(gap, y, TOL, MAX_IT, HALVINGS)
    f2 = fit_ordered(0.37 * gap, y, TOL, MAX_IT, HALVINGS)
    assert f2.slope == pytest.approx(f.slope / 0.37, rel=1e-9)
    assert f2.cut_away_draw == pytest.approx(f.cut_away_draw, abs=1e-9)
    assert f2.cut_draw_home == pytest.approx(f.cut_draw_home, abs=1e-9)
    assert np.abs(match_nll(f, gap, y) - match_nll(f2, 0.37 * gap, y)).max() < 1e-12


def test_a_missing_outcome_has_no_finite_fit() -> None:
    gap = np.array([-50.0, 10.0, 20.0, 60.0])
    with pytest.raises(FitError, match="no draw"):
        fit_ordered(gap, np.array([AWAY, HOME, AWAY, HOME]), TOL, MAX_IT, HALVINGS)
    with pytest.raises(FitError, match="no draw"):
        fit_ordered(None, np.array([AWAY, HOME, AWAY, HOME]), TOL, MAX_IT, HALVINGS)


@pytest.mark.parametrize("sign", [1, -1])
def test_a_gap_that_separates_the_outcomes_has_no_finite_fit(sign: int) -> None:
    gap = sign * np.array([-90.0, -40.0, -40.0, 5.0, 30.0, 30.0, 80.0])
    y = np.array([AWAY, AWAY, DRAW, DRAW, DRAW, HOME, HOME])  # ties at the boundaries
    with pytest.raises(FitError, match="separates"):
        fit_ordered(gap, y, TOL, MAX_IT, HALVINGS)


def test_identical_gaps_have_no_unique_fit() -> None:
    with pytest.raises(FitError, match="separates"):
        fit_ordered(np.full(6, 25.0), np.array([AWAY, DRAW, HOME, HOME, DRAW, AWAY]), TOL,
                    MAX_IT, HALVINGS)


def test_one_overlapping_match_makes_the_fit_finite() -> None:
    gap = np.array([-90.0, -40.0, -45.0, 5.0, 30.0, 35.0, 80.0, -60.0])
    y = np.array([AWAY, AWAY, DRAW, DRAW, DRAW, HOME, HOME, HOME])
    assert math.isfinite(fit_ordered(gap, y, TOL, MAX_IT, HALVINGS).slope)


def test_newton_raphson_that_doesnt_converge_stops_loudly() -> None:
    gap, y = simulate(300, 4)
    with pytest.raises(FitError, match="didn't converge in 2 iterations"):
        fit_ordered(gap, y, TOL, 2, HALVINGS)


def test_a_missing_gap_stops_loudly() -> None:
    gap, y = simulate(30, 5)
    gap[3] = np.nan
    with pytest.raises(FitError, match="missing"):
        fit_ordered(gap, y, TOL, MAX_IT, HALVINGS)


def baseline_start(gap: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float, np.ndarray]:
    """The fit's start (the baseline's cut-points, slope 0), its log-likelihood and the full
    Newton step from it."""
    share = np.cumsum([(y == k).sum() for k in (AWAY, DRAW)]) / len(y)
    start = np.append(np.log(share / (1 - share)), 0.0)
    step, _ = bf._newton_step(start, gap, y)
    return start, bf._loglik(start, gap, y), step


def test_a_step_that_overshoots_is_halved_until_the_likelihood_doesnt_fall() -> None:
    gap, y = simulate(300, 6)
    start, ll, step = baseline_start(gap, y)
    big = 40 * step  # far past the maximum along the Newton direction
    assert bf._loglik(start + big, gap, y) < ll
    new, new_ll = bf._line_search(start, big, ll, gap, y, HALVINGS)
    assert new_ll >= ll and new_ll == bf._loglik(new, gap, y)
    t = (new - start)[2] / big[2]
    assert t < 1 and math.log2(1 / t) == pytest.approx(round(math.log2(1 / t)), abs=1e-9)
    # The first halving that doesn't fall is the one taken, not a later, smaller one.
    assert bf._loglik(start + 2 * t * big, gap, y) < ll


def test_a_step_that_never_improves_within_the_cap_stops_loudly() -> None:
    gap, y = simulate(300, 7)
    start, ll, step = baseline_start(gap, y)
    with pytest.raises(FitError, match="no improvement after 5 halvings"):
        bf._line_search(start, -step, ll, gap, y, 5)  # downhill: every t > 0 is worse


def test_the_fit_passes_its_halving_cap_to_the_line_search(
        monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []
    real = bf._line_search

    def spy(params: np.ndarray, step: np.ndarray, ll: float, gap: np.ndarray, y: np.ndarray,
            max_halvings: int) -> tuple[np.ndarray, float]:
        seen.append(max_halvings)
        return real(params, step, ll, gap, y, max_halvings)

    monkeypatch.setattr(bf, "_line_search", spy)
    fit_ordered(*simulate(300, 8), TOL, MAX_IT, 7)
    assert seen and set(seen) == {7}
