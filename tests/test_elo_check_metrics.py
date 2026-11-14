"""The Elo check's pure metrics, on small inputs with hand-computed answers."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from backtest.elo_metrics import (
    calibration,
    calibration_ok,
    gap_summary,
    league_means,
    poisson_nll,
    spearman,
    step_edges,
)

GOAL_EDGES = [0.0, 0.75, 1.25, 1.75]


def test_calibration_counts_means_and_marks_each_bin() -> None:
    pred = [0.5, 0.6, 1.0, 2.0]
    actual = [0, 1, 2, 1]
    out = calibration(pred, actual, GOAL_EDGES, tol=0.1, min_count=2, decimals=9)
    assert out.bin.tolist() == ["0-0.75", "0.75-1.25", "1.25-1.75", "1.75+"]
    assert out["count"].tolist() == [2, 1, 0, 1]
    assert out.mean_pred.iloc[0] == pytest.approx(0.55)
    assert out.mean_actual.iloc[0] == pytest.approx(0.5)
    assert out["diff"].iloc[0] == pytest.approx(-0.05)
    assert out.scored.tolist() == [True, False, False, False]
    assert out.passed.iloc[0] is True
    assert out.passed.iloc[1:].isna().all()  # unscored bins carry no verdict


def test_an_empty_bin_is_shown_with_no_means() -> None:
    out = calibration([0.1], [0], GOAL_EDGES, tol=0.1, min_count=1, decimals=9)
    empty = out[out["count"] == 0]
    assert len(empty) == 3 and empty.mean_pred.isna().all() and empty.mean_actual.isna().all()


def test_a_value_on_an_edge_goes_in_the_upper_bin() -> None:
    out = calibration([0.75, 1.75], [0, 0], GOAL_EDGES, tol=0.1, min_count=1, decimals=9)
    assert out["count"].tolist() == [0, 1, 0, 1]


def test_a_bin_of_exactly_min_count_is_scored_and_one_fewer_is_not() -> None:
    at = calibration([1.0] * 100, [1] * 100, GOAL_EDGES, tol=0.1, min_count=100, decimals=9)
    below = calibration([1.0] * 99, [1] * 99, GOAL_EDGES, tol=0.1, min_count=100, decimals=9)
    assert at.scored.iloc[1] and not below.scored.iloc[1]


def test_a_gap_of_exactly_the_tolerance_passes_and_just_over_fails() -> None:
    # Mean actual 1.1 against 1.0 is 0.10000000000000009 in floating point.
    on = calibration([1.0] * 10, [1] * 9 + [2], GOAL_EDGES, tol=0.1, min_count=10, decimals=9)
    over = calibration([0.99] * 10, [1] * 9 + [2], GOAL_EDGES, tol=0.1, min_count=10, decimals=9)
    assert bool(on.passed.iloc[1]) and not bool(over.passed.iloc[1])


def test_calibration_ok_needs_every_scored_bin_within() -> None:
    good = calibration([0.5] * 4 + [2.0], [0, 1, 0, 1, 9], GOAL_EDGES, 0.1, 4, 9)
    bad = calibration([0.5] * 4, [1, 1, 1, 1], GOAL_EDGES, 0.1, 4, 9)
    assert calibration_ok(good)  # the 1.75+ bin is off by 7 but has one row, so no mark
    assert not calibration_ok(bad)


def test_clean_sheet_edges_step_by_a_tenth_and_the_top_bin_holds_one() -> None:
    edges = step_edges(0.1)
    assert edges == pytest.approx([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
    out = calibration([0.0, 0.1, 0.95, 1.0], [0, 1, 1, 1], edges, 0.05, 1, 9)
    assert out.bin.iloc[0] == "0-0.1" and out.bin.iloc[-1] == "0.9+"
    assert out["count"].tolist() == [1, 1, 0, 0, 0, 0, 0, 0, 0, 2]


def test_spearman_is_the_correlation_of_ranks() -> None:
    assert spearman(pd.Series([1, 2, 3, 4]), pd.Series([10, 20, 40, 30])) == pytest.approx(0.8)
    ties = spearman(pd.Series([1, 1, 2]), pd.Series([1, 2, 3]))
    assert ties == pytest.approx(1.5 / math.sqrt(3))


def test_gap_summary_reports_pairs_spearman_and_signed_and_absolute_gaps() -> None:
    pairs = pd.DataFrame({"elo_before": [1500.0, 1600.0, 1700.0],
                          "upstream_elo": [1510.0, 1590.0, 1720.0]})
    out = gap_summary(pairs)
    assert out["n"] == 3 and out["spearman"] == pytest.approx(1.0)
    assert out["mean_gap"] == pytest.approx((-10 + 10 - 20) / 3)
    assert out["mean_abs_gap"] == pytest.approx(40 / 3)


def test_gap_summary_of_one_pair_has_no_spearman() -> None:
    out = gap_summary(pd.DataFrame({"elo_before": [1.0], "upstream_elo": [2.0]}))
    assert out["n"] == 1 and np.isnan(out["spearman"])


def test_poisson_nll_matches_hand_values() -> None:
    out = poisson_nll(np.array([1.0, 2.0, 1.0]), np.array([0, 1, 2]))
    assert out == pytest.approx([1.0, 2.0 - math.log(2.0), 1.0 + math.log(2.0)])


def test_poisson_nll_rejects_a_non_positive_rate() -> None:
    with pytest.raises(ValueError, match="positive"):
        poisson_nll(np.array([0.0]), np.array([0]))


def test_league_means_are_home_and_away_goals_per_match() -> None:
    pool = pd.DataFrame({"home_goals": [1, 3], "away_goals": [0, 2]})
    assert league_means(pool) == (2.0, 1.0)


def test_league_means_of_an_empty_pool_raise() -> None:
    with pytest.raises(ValueError, match="empty"):
        league_means(pd.DataFrame({"home_goals": [], "away_goals": []}))


def test_known_output_regression() -> None:
    """Fixed input, fixed output: refactors must not change these numbers."""
    rng = np.random.default_rng(7)
    pred = rng.uniform(0.3, 2.5, 400)
    actual = rng.poisson(pred)
    goals = calibration(pred, actual, GOAL_EDGES, 0.1, 100, 9)
    # Values computed with a plain loop over the same draws, not with these functions.
    assert goals["count"].tolist() == [89, 82, 89, 140]
    assert goals.mean_actual.round(6).tolist() == [0.494382, 1.109756, 1.393258, 2.2]
    nll = poisson_nll(pred, actual).mean()
    assert round(float(nll), 6) == 1.391696
