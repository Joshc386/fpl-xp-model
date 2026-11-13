"""Known-output regression: fixed tables and settings give these ratings and lambdas.

If a change moves these numbers, it changed the model. Update them only on purpose, and say
so in docs/decisions.md. Checked by hand (2026-11-13, after re-seeding was introduced):
* Season B GW1: code 33, re-seeded at 1570 (its season A last-match value), beats code 35
  (seeded 1480) 2-1: E = 1 / (1 + 10^(-140/400)) = 0.691237, so +20 x 0.308763 = +6.1753.
* GW1: code 31 (1620) loses 0-1 at home to code 32 (1520): 20 x -0.703385 = -14.0677.
* GW2: 35 (1473.8247) draws at home with 31 (1605.9323): E = 0.384053, +2.3189, giving
  1476.1449 and 1603.6121. 32 (1534.0677) draws with 33 (1576.1753): -0.2272.
* Lambda: club 33 (1576.4024) at home to club 32 (1533.8406), gap 42.5618:
  exp(0.186288 + 0.00235858 x 42.5618 + 0.096390) = 1.46677.
"""

from __future__ import annotations

import pytest

from elo_tables import PREM, SETTINGS, two_seasons
from fpl.models.elo import run_elo
from fpl.models.team_goals import GoalsSettings, goals_from_history

GOALS = GoalsSettings(pool_seasons=2, min_matches=5, tol=1e-10, max_iter=50, max_horizon=2)


def test_known_ratings() -> None:
    ratings = run_elo(two_seasons(), SETTINGS, PREM).ratings
    assert ratings == pytest.approx({31: 1603.612088, 32: 1533.840577, 33: 1576.402400,
                                     34: 1431.473730, 35: 1476.144935}, abs=1e-6)


def test_known_goals_model() -> None:
    out, fit = goals_from_history(two_seasons(), SETTINGS, GOALS, PREM)
    assert (fit.intercept, fit.gap, fit.home) == pytest.approx(
        (0.186288362, 0.002358576, 0.096390147), abs=1e-9)
    assert (fit.n_matches, fit.mean_goals) == (10, 1.3)
    assert out.team_id.tolist() == [1, 4, 3, 2] and out.home.tolist() == [True, False] * 2
    assert out.lambda_for.tolist() == pytest.approx([1.466772, 1.089701, 1.791977, 0.891943],
                                                    abs=1e-6)
    assert out.p_cs.tolist() == pytest.approx([0.336317, 0.230669, 0.409858, 0.166630], abs=1e-6)
