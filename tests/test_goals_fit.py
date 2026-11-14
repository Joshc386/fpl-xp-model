"""The Elo goals model's fit: a log-linear Poisson with zero-centred priors on gap and home.

log lambda = intercept + gap_coef * gap + home_coef * home. The gap and home coefficients carry
Gaussian priors (precisions); the intercept carries none, so the fitted total equals the pool's.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from fpl.models.team_goals import GoalsModelError, poisson_fit

NO_PRIOR = np.zeros(3)
PRIOR = np.array([0.0, 1 / 0.00175**2, 1 / 0.175**2])
# Cell means 1, 2, 1.5, 3 at (gap, home) = (0,0), (100,0), (0,1), (100,1) are exactly
# log-linear, so the unpenalised MLE is log mu = 0 + gap x ln2/100 + home x ln1.5.
CELLS = [((0, 0), [0, 1, 2]), ((100, 0), [1, 2, 3]), ((0, 1), [1, 2]), ((100, 1), [2, 3, 4])]
X = np.array([[1.0, g, h] for (g, h), ys in CELLS for _ in ys])
Y = np.array([float(v) for _, ys in CELLS for v in ys])


def fit(precision: np.ndarray, x: np.ndarray = X, y: np.ndarray = Y) -> np.ndarray:
    return poisson_fit(x, y, precision, tol=1e-12, max_iter=100)


def penalised_loglik(beta: np.ndarray, precision: np.ndarray) -> float:
    """Poisson log-likelihood (without the log y! term) minus the prior's quadratic penalty."""
    eta = X @ beta
    return float(np.sum(Y * eta - np.exp(eta)) - 0.5 * np.sum(precision * beta**2))


def test_without_a_prior_the_fit_recovers_log_linear_cell_means() -> None:
    assert fit(NO_PRIOR) == pytest.approx([0.0, 0.006931472, 0.405465108], abs=1e-8)


def test_with_an_intercept_only_the_fit_is_the_log_mean() -> None:
    beta = fit(np.zeros(1), np.ones((4, 1)), np.array([0.0, 1.0, 2.0, 5.0]))
    assert beta == pytest.approx([math.log(2.0)])


def test_the_penalised_fit_is_a_stationary_point_of_the_penalised_likelihood() -> None:
    beta = fit(PRIOR)
    for j, h in enumerate([1e-6, 1e-8, 1e-6]):  # central differences, scaled per coefficient
        step = np.zeros(3)
        step[j] = h
        slope = (penalised_loglik(beta + step, PRIOR)
                 - penalised_loglik(beta - step, PRIOR)) / (2 * h)
        assert slope == pytest.approx(0.0, abs=1e-4)


def test_the_prior_shrinks_the_gap_and_home_terms_but_never_the_total() -> None:
    free, mild, strong = (fit(PRIOR * scale) for scale in (0, 1, 4))
    assert 0 < strong[1] < mild[1] < free[1]
    assert 0 < strong[2] < mild[2] < free[2]
    for beta in (free, mild, strong):  # the intercept is unpenalised: fitted total = actual
        assert np.exp(X @ beta).sum() == pytest.approx(Y.sum())


def test_an_overwhelming_prior_predicts_the_pool_mean_for_every_row() -> None:
    beta = fit(np.array([0.0, 1e14, 1e14]))
    assert np.exp(X @ beta) == pytest.approx(np.full(len(Y), Y.mean()), abs=1e-6)


def test_a_prior_makes_a_fit_possible_where_the_data_cannot_identify_the_gap() -> None:
    flat = np.column_stack([np.ones(4), np.zeros(4), [1.0, 1.0, 0.0, 0.0]])  # every gap 0
    y = np.array([2.0, 1.0, 1.0, 1.0])
    with pytest.raises(GoalsModelError, match="singular"):
        fit(NO_PRIOR, flat, y)
    assert fit(PRIOR, flat, y)[1] == 0.0


def test_a_pool_without_goals_raises() -> None:
    with pytest.raises(GoalsModelError, match="no goals"):
        fit(PRIOR, X, np.zeros(len(Y)))


def test_a_fit_that_does_not_converge_raises() -> None:
    x = np.column_stack([np.ones(4), [0.0, 1.0, 2.0, 3.0]])
    with pytest.raises(GoalsModelError, match="converge"):
        poisson_fit(x, np.array([1.0, 0.0, 3.0, 9.0]), np.zeros(2), tol=1e-12, max_iter=1)
