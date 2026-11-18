"""The outside-source Elo check's verdict (`CONTEXT.md` **Poor Elo rating**), on per-match losses
built so that each condition fires on its own, both fire, or neither does."""

from __future__ import annotations

import math

import numpy as np
import pytest
from backtest.beyondelo_fit import poor_elo_verdict

K, DEC = 2.0, 9


def verdict(ours: list[float], theirs: list[float], base: list[float]) -> dict:
    return poor_elo_verdict(np.array(ours), np.array(theirs), np.array(base), K, DEC)


def test_neither_condition_fires_when_ours_matches_beyondelo_and_beats_the_baseline() -> None:
    v = verdict([0.9, 1.1, 1.0, 1.0], [1.0, 1.0, 1.1, 0.9], [1.1] * 4)
    assert v["mean"] == pytest.approx(0.0, abs=1e-15)
    assert not v["worse_than_beyondelo"] and not v["not_below_baseline"] and not v["poor"]
    assert v["n"] == 4


def test_condition_one_alone_fires_when_ours_is_clearly_worse_than_beyondelo() -> None:
    ours = [1.00, 1.02, 0.98, 1.01]
    theirs = [0.90, 0.91, 0.89, 0.90]
    v = verdict(ours, theirs, [1.2] * 4)
    d = np.array(ours) - np.array(theirs)
    assert v["mean"] == pytest.approx(d.mean(), abs=1e-15)
    assert v["sd"] == pytest.approx(d.std(ddof=1), abs=1e-15)
    assert v["se"] == pytest.approx(d.std(ddof=1) / 2, abs=1e-15)
    assert v["threshold"] == pytest.approx(2 * v["se"], abs=1e-15)
    assert v["worse_than_beyondelo"] and not v["not_below_baseline"] and v["poor"]


def test_condition_two_alone_fires_when_ours_is_not_below_the_baseline() -> None:
    v = verdict([1.1, 0.9, 1.0, 1.0], [1.0, 1.0, 0.9, 1.1], [1.0] * 4)
    assert v["ours"] == pytest.approx(1.0) and v["baseline"] == pytest.approx(1.0)
    assert not v["worse_than_beyondelo"] and v["not_below_baseline"] and v["poor"]


def test_both_conditions_can_fire_together() -> None:
    v = verdict([1.3, 1.31, 1.29, 1.3], [1.0, 1.01, 0.99, 1.0], [1.1] * 4)
    assert v["worse_than_beyondelo"] and v["not_below_baseline"] and v["poor"]


def test_a_mean_exactly_two_standard_errors_above_zero_is_not_poor() -> None:
    # Differences m+x, m-x, m+x, m-x: sd = 2x/sqrt(3), SE = x/sqrt(3), so m = 2x/sqrt(3) sits
    # exactly on the two-SE line ("more than two standard errors" fails only above it).
    x = 0.03
    m = 2 * x / math.sqrt(3)
    theirs = [1.0, 1.0, 1.0, 1.0]
    ours = [1.0 + m + x, 1.0 + m - x, 1.0 + m + x, 1.0 + m - x]
    v = verdict(ours, theirs, [2.0] * 4)
    assert v["mean"] == pytest.approx(v["threshold"], abs=1e-12)
    assert not v["worse_than_beyondelo"]
    above = verdict([o + 1e-6 for o in ours], theirs, [2.0] * 4)
    assert above["worse_than_beyondelo"] and above["poor"]


def test_identical_losses_have_zero_sd_and_are_not_poor() -> None:
    v = verdict([0.8, 1.2, 1.0], [0.8, 1.2, 1.0], [1.1, 1.1, 1.1])
    assert v["sd"] == 0.0 and v["se"] == 0.0 and v["threshold"] == 0.0
    assert not v["worse_than_beyondelo"] and not v["poor"]


def test_a_constant_positive_difference_has_zero_sd_and_is_poor() -> None:
    v = verdict([0.81, 1.21, 1.01], [0.8, 1.2, 1.0], [1.5, 1.5, 1.5])
    assert v["sd"] == pytest.approx(0.0, abs=1e-12)
    assert v["worse_than_beyondelo"] and v["poor"]


def test_floating_point_noise_around_zero_is_not_poor() -> None:
    # An affine copy of our ratings gives per-match differences at rounding level only.
    rng = np.random.default_rng(0)
    theirs = rng.uniform(0.5, 1.5, 199)
    ours = theirs + rng.normal(0.0, 1e-15, 199) + 1e-15
    v = poor_elo_verdict(ours, theirs, theirs + 0.1, K, DEC)
    assert not v["worse_than_beyondelo"] and not v["poor"]


def test_fewer_than_two_matches_stops() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        verdict([1.0], [1.0], [1.0])
