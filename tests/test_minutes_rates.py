"""The minutes component's per-player rates, checked against hand-computed values (brief 6.1):
the gameweek weights, the history from `recent_minutes`, the counts, the position priors and
the shrunk rates."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fpl.features import recent_minutes
from fpl.models.minutes_rates import (
    RATES,
    MinutesError,
    gameweek_counts,
    gameweek_history,
    gameweek_weights,
    player_rates,
    position_priors,
)
from minutes_tables import PREM, tables


def observed(history: pd.DataFrame, player: int) -> list[tuple[int, int, int, int]]:
    """(recency, minutes, starts, fixtures) rows of one player, most recent first."""
    h = history[history.player_id == player].sort_values("recency")
    return list(h[["recency", "minutes", "starts", "fixtures"]].itertuples(index=False, name=None))


def test_each_gameweek_weighs_the_share_of_windows_that_hold_it() -> None:
    # Windows 1, 3 and 6, equal weights: the last gameweek is in all three windows, the two
    # before it in two, and the three before those in one.
    assert gameweek_weights([1, 3, 6], [1, 1, 1]) == pytest.approx(
        [1, 2 / 3, 2 / 3, 1 / 3, 1 / 3, 1 / 3])
    # Unequal weights 3, 2, 1 (sum 6): 6/6, then (2 + 1)/6 twice, then 1/6 three times.
    assert gameweek_weights([1, 3, 6], [3, 2, 1]) == pytest.approx(
        [1, 0.5, 0.5, 1 / 6, 1 / 6, 1 / 6])
    assert gameweek_weights([2], [5]) == pytest.approx([1, 1])


@pytest.mark.parametrize(("windows", "weights"), [
    ([1, 3], [1, 1, 1]),   # lengths differ
    ([3, 1], [1, 1]),      # not increasing
    ([1, 1], [1, 1]),      # not distinct
    ([0, 3], [1, 1]),      # not positive
    ([1, 3], [1, 0]),      # a zero weight
    ([], []),              # no window
])
def test_bad_windows_or_weights_are_rejected(windows: list[int], weights: list[float]) -> None:
    with pytest.raises(MinutesError):
        gameweek_weights(windows, weights)


def test_the_weights_are_a_float_array() -> None:
    out = gameweek_weights([1, 3, 6], [1, 1, 1])
    assert isinstance(out, np.ndarray) and out.dtype == np.float64


def test_history_has_one_row_per_gameweek_with_a_club_fixture_most_recent_first() -> None:
    # Club 1 plays GW1, 2 (a double), 4 and 5; GW3 is its blank. Player 10 is at club 1.
    t = tables(
        [(10, 1, 1, 90, 1), (10, 1, 2, 150, 2), (10, 1, 3, 0, 0), (10, 1, 4, 20, 0),
         (10, 1, 5, 75, 1)],
        [(1, 1, 2), (2, 1, 2), (2, 2, 1), (3, 2, 3), (4, 1, 3), (5, 3, 1)],
    )
    h = gameweek_history(t, 5, 6, PREM)
    assert list(h.columns) == ["player_id", "recency", "minutes", "starts", "fixtures"]
    # GW5, GW4, the double GW2, GW1; the blank GW3 is skipped, and there is no fifth gameweek.
    assert observed(h, 10) == [(0, 75, 1, 1), (1, 20, 0, 1), (2, 150, 2, 2), (3, 90, 1, 1)]


def test_history_follows_the_club_of_each_gameweek_and_skips_later_gameweeks() -> None:
    # Player 11 moves from club 1 to club 2 for GW3; club 1 is blank in GW3, club 2 is not.
    t = tables(
        [(11, 1, 1, 90, 1), (11, 1, 2, 60, 1), (11, 2, 3, 30, 0), (11, 2, 4, 90, 1)],
        [(1, 1, 2), (2, 1, 2), (3, 2, 3), (4, 1, 2)],
    )
    assert observed(gameweek_history(t, 3, 6, PREM), 11) == [
        (0, 30, 0, 1), (1, 60, 1, 1), (2, 90, 1, 1)]


def test_history_reaches_back_as_far_as_the_depth_and_no_further() -> None:
    t = tables([(10, 1, g, 10 * g, 1) for g in range(1, 6)], [(g, 1, 2) for g in range(1, 6)])
    assert [r for r, *_ in observed(gameweek_history(t, 5, 3, PREM), 10)] == [0, 1, 2]
    assert [r for r, *_ in observed(gameweek_history(t, 5, 9, PREM), 10)] == [0, 1, 2, 3, 4]


def test_history_sums_to_the_recent_minutes_window_totals() -> None:
    t = tables(
        [(p, 1 + p % 2, g, (7 * p + 13 * g) % 91, int((p + g) % 3 > 0))
         for p in (10, 11, 12, 13) for g in range(1, 9)],
        [(g, 1, 2) for g in range(1, 9)] + [(5, 2, 3), (7, 1, 3)],
    )
    h = gameweek_history(t, 8, 6, PREM)
    totals = recent_minutes(t, 8, [1, 3, 6], PREM).set_index(["player_id", "window"])
    for n in (1, 3, 6):
        part = h[h.recency < n].groupby("player_id")[["minutes", "starts", "fixtures"]].sum()
        want = totals.xs(n, level="window").loc[part.index, ["minutes", "starts", "fixtures"]]
        pd.testing.assert_frame_equal(part, want)


def test_a_player_with_no_gameweek_yet_has_no_history_rows() -> None:
    t = tables([(10, 1, 1, 90, 1)], [(1, 1, 2)], players=[(10, 1, "MID", "a", None),
                                                          (12, 2, "DEF", "a", None)])
    h = gameweek_history(t, 1, 6, PREM)
    assert observed(h, 12) == [] and observed(h, 10) == [(0, 90, 1, 1)]


def history_frame(rows: list[tuple]) -> pd.DataFrame:
    """A `gameweek_history` frame from (player, recency, minutes, starts, fixtures) rows."""
    return pd.DataFrame(rows, columns=["player_id", "recency", "minutes", "starts", "fixtures"])


def test_counts_split_single_fixture_gameweeks_into_starts_and_bench_outcomes() -> None:
    c = gameweek_counts(history_frame([
        (10, 0, 90, 1, 1),    # a start that reaches 60
        (10, 1, 59, 1, 1),    # a start that doesn't
        (10, 2, 60, 1, 1),    # exactly 60 counts
        (10, 3, 25, 0, 1),    # a bench appearance
        (10, 4, 0, 0, 1),     # not used
        (10, 5, 65, 0, 1),    # off the bench for 60+ minutes: not a start that reached 60
    ]), long_minutes=60)
    assert c.starts.tolist() == [1, 1, 1, 0, 0, 0] and c.fixtures.tolist() == [1] * 6
    assert c.start_obs.tolist() == [1, 1, 1, 0, 0, 0]
    assert c.start_60.tolist() == [1, 0, 1, 0, 0, 0]
    assert c.start_minutes.tolist() == [90, 59, 60, 0, 0, 0]
    assert c.bench_obs.tolist() == [0, 0, 0, 1, 1, 1]
    assert c.bench_apps.tolist() == [0, 0, 0, 1, 0, 1]
    assert c.bench_minutes.tolist() == [0, 0, 0, 25, 0, 65]


def test_a_double_gameweek_counts_in_the_start_rate_only() -> None:
    # FPL gives minutes per gameweek, so which start reached 60, and whether the 40 minutes of
    # the second row were a start or a bench appearance, is unknown.
    c = gameweek_counts(history_frame([(10, 0, 160, 2, 2), (10, 1, 130, 1, 2)]), 60)
    assert c.starts.tolist() == [2, 1] and c.fixtures.tolist() == [2, 2]
    for col in ("start_obs", "start_60", "start_minutes", "bench_obs", "bench_apps",
                "bench_minutes"):
        assert c[col].tolist() == [0, 0], col


def test_the_60_minute_line_comes_from_the_argument() -> None:
    c = gameweek_counts(history_frame([(10, 0, 70, 1, 1), (10, 1, 75, 1, 1)]), long_minutes=75)
    assert c.start_60.tolist() == [0, 1]


def test_priors_pool_each_position_and_fall_back_to_the_league() -> None:
    counts = gameweek_counts(history_frame([
        (10, 0, 90, 1, 1), (10, 1, 50, 1, 1), (10, 2, 20, 0, 1),   # MID
        (11, 0, 70, 1, 1), (11, 1, 0, 0, 1),                       # MID
        (1, 0, 90, 1, 1), (1, 1, 90, 1, 1),                        # GKP, never benched
        (99, 0, 10, 1, 1),                                         # left: no position
    ]), 60)
    positions = pd.Series({10: "MID", 11: "MID", 1: "GKP", 12: "DEF"}, name="position")
    p = position_priors(counts, positions)
    assert sorted(p.index) == ["DEF", "GKP", "MID"]
    assert list(p.columns) == ["start_rate", *RATES]
    # MID: 3 starts in 5 fixtures, then the four rates.
    assert p.loc["MID"].tolist() == pytest.approx([3 / 5, 2 / 3, 70, 0.5, 20])
    # The goalkeeper never missed a start, so his bench rates are the league's (MID + GKP).
    assert p.loc["GKP"].tolist() == pytest.approx([1, 1, 90, 0.5, 20])
    # No defender has a gameweek: every rate is the league's (5 starts in 7 fixtures).
    assert p.loc["DEF"].tolist() == pytest.approx([5 / 7, 4 / 5, 78, 0.5, 20])


def test_with_no_observation_anywhere_a_prior_is_zero() -> None:
    p = position_priors(gameweek_counts(history_frame([]), 60), pd.Series({1: "GKP"}))
    assert p.loc["GKP"].tolist() == [0, 0, 0, 0, 0]


U = gameweek_weights([1, 3, 6], [1, 1, 1])   # [1, 2/3, 2/3, 1/3, 1/3, 1/3]
MID_PRIOR = {"start_rate": 0.3, "p60_given_start": 0.9, "minutes_given_start": 80.0,
             "bench_rate": 0.2, "minutes_given_bench": 18.0}
PRIORS = pd.DataFrame([MID_PRIOR, {**MID_PRIOR, "start_rate": 0.35, "p60_given_start": 0.95}],
                      index=pd.Index(["MID", "DEF"], name="position"))
PLAYER_10 = [(10, 0, 90, 1, 1), (10, 1, 20, 0, 1), (10, 2, 55, 1, 1), (10, 3, 0, 0, 1),
             (10, 4, 90, 1, 1), (10, 5, 70, 1, 1)]


def rates_of(rows: list[tuple], positions: dict[int, str], k: float = 1.0) -> pd.DataFrame:
    counts = gameweek_counts(history_frame(rows), 60)
    return player_rates(counts, pd.Series(positions), U, PRIORS, k)


def test_rates_are_recency_weighted_and_shrunk_toward_the_position_prior() -> None:
    r = rates_of(PLAYER_10, {10: "MID"}).loc[10]
    # Starts 1 + 2/3 + 1/3 + 1/3 = 7/3 over fixtures 10/3.
    assert r.start_rate == pytest.approx(0.7)
    # 60s 1 + 1/3 + 1/3 = 5/3 of 7/3 weighted starts, plus k = 1 at the prior 0.9.
    assert r.p60_given_start == pytest.approx((5 / 3 + 0.9) / (7 / 3 + 1))   # 0.77
    # Start minutes 90 + 2/3 * 55 + 1/3 * 90 + 1/3 * 70 = 180, plus 80 at the prior.
    assert r.minutes_given_start == pytest.approx(78.0)
    # Weighted non-starts 2/3 + 1/3 = 1, of which 2/3 a bench appearance (20 minutes).
    assert r.bench_rate == pytest.approx((2 / 3 + 0.2) / 2)
    assert r.minutes_given_bench == pytest.approx((2 / 3 * 20 + 18) / (2 / 3 + 1))   # 18.8


def test_a_larger_prior_strength_pulls_harder() -> None:
    weak, strong = rates_of(PLAYER_10, {10: "MID"}, 0.5), rates_of(PLAYER_10, {10: "MID"}, 50)
    assert weak.loc[10].p60_given_start < strong.loc[10].p60_given_start < 0.9
    assert weak.loc[10].start_rate == strong.loc[10].start_rate == pytest.approx(0.7)


def test_gameweeks_beyond_the_longest_window_are_ignored() -> None:
    older = PLAYER_10 + [(10, 6, 0, 0, 1), (10, 7, 0, 0, 1)]
    pd.testing.assert_frame_equal(rates_of(older, {10: "MID"}), rates_of(PLAYER_10, {10: "MID"}))


def test_a_double_gameweek_counts_two_fixtures_in_the_start_rate_only() -> None:
    r = rates_of([(11, 0, 150, 2, 2), (11, 1, 90, 1, 1)], {11: "DEF"}).loc[11]
    assert r.start_rate == pytest.approx(1.0)
    # Only the single GW (weight 2/3) informs the conditional rates; the bench ones are prior.
    assert r.p60_given_start == pytest.approx((2 / 3 + 0.95) / (2 / 3 + 1))
    assert r.minutes_given_start == pytest.approx((60 + 80) / (5 / 3))   # 84
    assert r.bench_rate == pytest.approx(0.2) and r.minutes_given_bench == pytest.approx(18)
    r2 = rates_of([(11, 0, 120, 1, 2), (11, 1, 0, 0, 1)], {11: "DEF"}).loc[11]
    assert r2.start_rate == pytest.approx(1 / (2 + 2 / 3))


def test_a_player_with_no_history_gets_his_positions_prior_rates() -> None:
    # Brief "Horizon and aggregation": a new arrival uses the prior (decided 2026-11-24).
    r = rates_of(PLAYER_10, {10: "MID", 12: "DEF"})
    assert sorted(r.index) == [10, 12]
    assert list(r.columns) == ["start_rate", *RATES]
    assert r.loc[12].tolist() == pytest.approx(PRIORS.loc["DEF"].tolist())
    assert r.loc[10].start_rate == pytest.approx(0.7)     # his own history, not the prior
