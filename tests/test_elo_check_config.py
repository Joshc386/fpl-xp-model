"""backtest/config.yaml pinned against brief section 7 and the contract's Elo seed notes.

A change to any value here is a change to the gate, which is Josh's decision: update the brief
first, then this test.
"""

from __future__ import annotations

import pytest
from backtest.elo_check import expected_skips, load_settings

from fpl.models.elo import MissingSeedError
from fpl.models.team_goals import InsufficientSampleError

S = load_settings()


def gameweeks(ranges: list[list[int]]) -> set[int]:
    return {g for lo, hi in ranges for g in range(lo, hi + 1)}


def test_mode_seasons_and_window() -> None:
    assert S["mode"] == "backtest"
    assert S["seasons"] == [{"id": "2025-2026", "target_gameweeks": [1, 38]},
                            {"id": "2026-2027", "target_gameweeks": [1, 10]}]
    assert S["baseline_pool_seasons"] == 2  # this season and last
    assert S["pass_from_gw"] == 6


def test_calibration_marks() -> None:  # M37
    assert S["goals"] == {"bin_edges": [0.0, 0.75, 1.25, 1.75], "tolerance": 0.1}
    assert S["clean_sheets"] == {"bin_width": 0.1, "tolerance": 0.05}
    assert S["min_bin_count"] == 100
    assert S["calibration_k"] == 2


def test_ratings_marks() -> None:  # M39
    r = S["ratings"]
    assert r["season"] == "2025-2026" and r["min_spearman"] == 0.9
    assert gameweeks(r["pass_gameweeks"]) == set(range(6, 27)) | {33}
    unscored = gameweeks([u["range"] for u in r["unscored"]])
    assert unscored == set(range(1, 6)) | set(range(27, 33)) | set(range(34, 39))
    assert not unscored & gameweeks(r["pass_gameweeks"])


def test_expected_skips_are_exactly_the_contracts() -> None:  # M38
    want = {
        "elo_ratings": {"2025-2026": {0: MissingSeedError},
                        "2026-2027": {0: MissingSeedError, 1: MissingSeedError}},
        "elo_goals": {"2025-2026": {0: MissingSeedError, 1: InsufficientSampleError,
                                    2: InsufficientSampleError},
                      "2026-2027": {0: MissingSeedError, 1: MissingSeedError}},
    }
    assert expected_skips(S) == want


def test_perturbation_cases_are_the_briefs() -> None:
    p = S["perturbation"]
    assert [(c["season"], c["as_of"]) for c in p["cases"]] == [
        ("2025-2026", 5), ("2025-2026", 20), ("2025-2026", 33), ("2026-2027", 3),
        ("2026-2027", 9)]
    assert {"season": "2025-2026", "gw": 33} in p["within_gameweek"]  # the double gameweek


def test_an_unknown_exception_name_is_rejected() -> None:
    with pytest.raises(KeyError):
        expected_skips({"expected_skips": {"elo_goals": {"2025-2026": {0: "ValueError"}}}})
