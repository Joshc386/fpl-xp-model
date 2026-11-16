"""The refit rule (brief section 7, "The refit check") on hand-built goal checks and pools.

Between consecutive as-of reads of the goals model, the fitted coefficients must change (by more
than the tolerance) when the fitting pool changed, and must not change when it is identical.
"""

from __future__ import annotations

import pandas as pd
import pytest
from backtest.elo_check import criteria
from backtest.elo_data import refit_pairs

ORDER = ["S1", "S2"]
TOL = 0.25  # exact in binary, so the edge is exact


def results(season: str, gws: dict[str, int]) -> pd.DataFrame:
    """Finished league results (as `match_results` returns them): match id -> gameweek."""
    return pd.DataFrame({"season": season, "match_id": list(gws), "gw": list(gws.values())})


# S1: GW3 has no result (wholly postponed). S2: one result in GW1.
POOLS = {"S1": results("S1", {"m1": 1, "m2": 2, "m3": 4}), "S2": results("S2", {"n1": 1})}


def checks(*rows: tuple[str, int, float]) -> pd.DataFrame:
    """Goal-check rows (season, as-of, intercept); the gap and home coefficients are fixed."""
    return pd.DataFrame([{"season": x, "as_of": a, "intercept": c, "gap": 0.002, "home": 0.2}
                         for x, a, c in rows])


def pairs(c: pd.DataFrame) -> pd.DataFrame:
    return refit_pairs(c, POOLS, ORDER, 2, TOL)


HONEST = checks(("S1", 1, 1.0), ("S1", 2, 2.0), ("S1", 3, 2.0), ("S1", 4, 3.0), ("S2", 1, 4.0))


def test_a_refit_at_every_new_result_and_none_at_a_postponed_gameweek_passes() -> None:
    out = pairs(HONEST)
    assert len(out) == 4
    assert out.pool_changed.tolist() == [True, False, True, True]  # S1 as-of 3 gained nothing
    assert out.coef_changed.tolist() == [True, False, True, True]
    assert out.ok.all()


def test_the_pairs_name_both_reads_in_the_goal_checks_order() -> None:
    out = pairs(HONEST)
    assert list(zip(out.from_season, out.from_as_of, out.to_season, out.to_as_of,
                    strict=True)) == [("S1", 1, "S1", 2), ("S1", 2, "S1", 3), ("S1", 3, "S1", 4),
                                      ("S1", 4, "S2", 1)]  # the season boundary included


def test_a_pool_that_gained_a_result_with_no_coefficient_change_fails() -> None:
    out = pairs(checks(("S1", 1, 1.0), ("S1", 2, 1.0)))
    assert out.pool_changed.tolist() == [True] and not out.ok.any()


def test_a_coefficient_change_with_an_identical_pool_fails() -> None:
    out = pairs(checks(("S1", 2, 2.0), ("S1", 3, 2.5)))
    assert out.pool_changed.tolist() == [False] and not out.ok.any()


def test_the_season_boundary_pair_is_checked_against_the_pool_across_seasons() -> None:
    # S1 to GW4 is S1 in full; S2 as-of 1 adds S2's GW1 result to it.
    out = pairs(checks(("S1", 4, 3.0), ("S2", 1, 3.0)))
    assert out.pool_changed.tolist() == [True] and not out.ok.any()


@pytest.mark.parametrize("field", ["intercept", "gap", "home"])
def test_a_change_in_any_coefficient_counts(field: str) -> None:
    c = checks(("S1", 2, 2.0), ("S1", 3, 2.0))
    c.loc[1, field] += 1.0
    out = pairs(c)
    assert out.coef_changed.tolist() == [True] and out.max_diff.tolist() == [1.0]


def test_a_change_of_exactly_the_tolerance_is_no_change() -> None:
    at = pairs(checks(("S1", 2, 2.0), ("S1", 3, 2.0 + TOL)))
    assert at.max_diff.tolist() == [TOL] and at.coef_changed.tolist() == [False]
    assert at.ok.all()  # the pool is unchanged, so no change is right
    above = pairs(checks(("S1", 2, 2.0), ("S1", 3, 2.0 + TOL + 2 ** -40)))
    assert above.coef_changed.tolist() == [True] and not above.ok.any()


def test_fewer_than_two_reads_give_no_pairs() -> None:
    assert len(pairs(HONEST.iloc[:1])) == 0
    assert len(pairs(HONEST.iloc[:0])) == 0
    assert len(refit_pairs(pd.DataFrame(), POOLS, ORDER, 2, TOL)) == 0  # no goal checks at all


# --- the criterion ----------------------------------------------------------------------

def met(refit: pd.DataFrame) -> bool:
    rt = pd.DataFrame({"gw": [6], "mark": ["pass mark"], "passed": [True]})
    pooled = {"goals_ok": True, "cs_ok": True, "beats_baseline": True}
    leak = {"after": [{"functions": {"elo_ratings": {"changed": 0}, "elo_goals": {"changed": 0},
                                     "planted_leak": {"changed": 5}},
                       "control": {"elo_ratings": {"changed": 3}, "elo_goals": {"changed": 2}}}],
            "within": [{"changed": 0, "control_changed": 4}]}
    stability = {"S1": {"changed": 0, "missing": 0, "extra": 0}}
    s = {"ratings": {"pass_gameweeks": [[6, 6]]}}
    return criteria(rt, pooled, leak, stability, refit, s)["refit"]


def test_the_refit_criterion_needs_every_pair_to_meet_the_rule() -> None:
    assert met(pairs(HONEST))
    frozen = HONEST.assign(intercept=1.0)
    assert not met(pairs(frozen))


def test_the_refit_criterion_needs_at_least_one_pair() -> None:
    assert not met(pairs(HONEST.iloc[:1]))
