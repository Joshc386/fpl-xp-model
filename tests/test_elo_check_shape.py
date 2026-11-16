"""The goals output's shape (brief 6.2, assuming no functional form) and its log-linear fit
(information about the current form), on small hand-built reads."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from backtest.elo_data import goals_shape, implied_coefficients


def preds(rows: list[tuple]) -> pd.DataFrame:
    cols = ["team_id", "match_id", "gw", "opponent_id", "home", "lambda_for", "lambda_against"]
    df = pd.DataFrame(rows, columns=cols)
    return df.assign(p_cs=np.exp(-df.lambda_against))


def ratings(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["team_id", "match_id", "season", "gw", "kickoff_utc",
                                       "elo_before", "elo_after"])


# --- the log-linear fit (information about the current form) and contract identities ---

def test_implied_coefficients_recover_a_log_linear_model_exactly() -> None:
    r = ratings([(1, "a", "S1", 1, "t1", 1500.0, 1560.0), (2, "a", "S1", 1, "t1", 1500.0, 1440.0),
                 (3, "b", "S1", 1, "t2", 1500.0, 1530.0), (4, "b", "S1", 1, "t2", 1500.0, 1480.0)])
    a, b, h = 0.1, 0.002, 0.25
    cur = {1: 1560.0, 2: 1440.0, 3: 1530.0, 4: 1480.0}  # gaps 30 and 40
    rows = []
    for mid, home, away in [("e", 1, 3), ("f", 4, 2)]:
        gap = cur[home] - cur[away]
        lh, la = math.exp(a + b * gap + h), math.exp(a - b * gap)
        rows += [(home, mid, 2, away, True, lh, la), (away, mid, 2, home, False, la, lh)]
    out = implied_coefficients(preds(rows), r, "S1")
    assert out["intercept"] == pytest.approx(a) and out["gap"] == pytest.approx(b)
    assert out["home"] == pytest.approx(h) and out["max_resid"] < 1e-9
    assert out["p_cs_err"] < 1e-12 and out["mirror_err"] < 1e-12 and out["unrated"] == 0


# --- the goals output's shape, assuming no functional form (brief 6.2) ----------------------

def shaped(cur: dict[int, float], fixtures: list[tuple[str, int, int]],
           lam: callable) -> tuple[pd.DataFrame, pd.DataFrame]:
    """A ratings read whose last elo_after per club is `cur`, and horizon predictions with
    lambda_for = lam(gap, home, team)."""
    r = ratings([(t, f"r{t}", "S1", 1, "t1", 1500.0, v) for t, v in cur.items()])
    rows = []
    for mid, h, a in fixtures:
        gap = cur[h] - cur[a]
        lh, la = lam(gap, True, h), lam(-gap, False, a)
        rows += [(h, mid, 2, a, True, lh, la), (a, mid, 2, h, False, la, lh)]
    return preds(rows), r


CUR = {1: 1600.0, 2: 1400.0, 3: 1550.0, 4: 1450.0, 5: 1500.0, 6: 1500.0}
FIX = [("e", 1, 2), ("f", 3, 4), ("g", 5, 6), ("h", 2, 3)]  # home gaps 200, 100, 0, -150


def test_a_log_linear_output_has_the_shape_and_zero_residual() -> None:
    p, r = shaped(CUR, FIX, lambda g, h, t: math.exp(0.1 + 0.002 * g + 0.25 * h))
    out = goals_shape(p, r, "S1", tol=1e-12)
    assert out["not_rising"] == 0 and out["tie_mismatch"] == 0 and out["unrated"] == 0
    assert out["home_above"] == 1.0 and out["n"] == 8
    assert implied_coefficients(p, r, "S1")["max_resid"] < 1e-9


def test_another_monotone_form_has_the_shape_but_not_a_zero_residual() -> None:
    p, r = shaped(CUR, FIX, lambda g, h, t: 1.4 + 0.003 * g + 0.3 * h)  # linear, not log-linear
    out = goals_shape(p, r, "S1", tol=1e-12)
    assert out["not_rising"] == 0 and out["tie_mismatch"] == 0 and out["home_above"] == 1.0
    assert implied_coefficients(p, r, "S1")["max_resid"] > 1e-3


def test_a_rate_that_falls_as_the_gap_rises_is_flagged() -> None:
    p, r = shaped(CUR, FIX, lambda g, h, t: math.exp(0.1 - 0.002 * g + 0.25 * h))
    assert goals_shape(p, r, "S1", tol=1e-12)["not_rising"] == 6  # 3 steps home, 3 away


def test_a_rate_that_depends_on_the_club_is_flagged() -> None:
    # Club 5 gets a bonus: at home with gap 0 it beats club 3 at home with gap 100.
    p, r = shaped(CUR, FIX, lambda g, h, t: math.exp(0.1 + 0.002 * g + 0.25 * h + (t == 5)))
    assert goals_shape(p, r, "S1", tol=1e-12)["not_rising"] >= 1


def test_equal_gaps_with_different_rates_are_flagged() -> None:
    cur = {1: 1600.0, 2: 1500.0, 3: 1700.0, 4: 1600.0}  # both home gaps are 100
    p, r = shaped(cur, [("e", 1, 2), ("f", 3, 4)],
                  lambda g, h, t: math.exp(0.002 * g + 0.25 * h + 0.1 * (t == 3)))
    assert goals_shape(p, r, "S1", tol=1e-12)["tie_mismatch"] == 1


def test_home_rows_below_the_away_curve_lower_the_home_share() -> None:
    p, r = shaped(CUR, FIX, lambda g, h, t: math.exp(0.002 * g - 0.25 * h))  # away advantage
    assert goals_shape(p, r, "S1", tol=1e-12)["home_above"] == 0.0


def test_a_rate_that_ignores_the_gap_is_flagged() -> None:
    p, r = shaped(CUR, FIX, lambda g, h, t: math.exp(0.1 + 0.25 * h))  # home only, flat in gap
    assert goals_shape(p, r, "S1", tol=1e-12)["not_rising"] == 6
