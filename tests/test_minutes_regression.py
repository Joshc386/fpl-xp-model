"""A known-output regression test for the minutes component: fixed tables, fixed settings.

Clubs 1 and 2 have the players; 3 and 4 are opponents. History GW1-7 (as-of 7): club 1 has a
double in GW5, club 2 a blank in GW4. Player 105 moves from club 2 to club 1 for GW5. The
horizon (3 gameweeks) has club 1's double in GW9 and its blank in GW10. Statuses: 102
doubtful (75, which scales GW8, the next gameweek, only), 103 available with a chance of 0
(2025/26's quirk), 104 injured, 201 not available, 203 a new signing with no gameweek yet
(so the DEF prior).
"""

from __future__ import annotations

import pandas as pd
import pytest

from fpl.models.minutes import MinutesSettings, minutes_from_tables
from minutes_tables import PREM, tables

SETTINGS = MinutesSettings(windows=(1, 3, 6), weights=(1.0, 1.0, 1.0), prior_strength=1.0,
                           second_fixture_discount=0.1, long_minutes=60, max_horizon=3)
# (minutes, starts) for GW1-7; club 1's GW5 is a double, club 2's GW4 a blank.
HISTORY = {
    (101, 1): [(90, 1), (90, 1), (90, 1), (90, 1), (180, 2), (90, 1), (90, 1)],
    (102, 1): [(90, 1), (55, 1), (0, 0), (90, 1), (150, 2), (90, 1), (70, 1)],
    (103, 1): [(0, 0), (25, 0), (90, 1), (15, 0), (100, 1), (0, 0), (64, 1)],
    (104, 1): [(90, 1), (90, 1), (80, 1), (90, 1), (90, 1), (0, 0), (0, 0)],
    (201, 2): [(90, 1), (90, 1), (90, 1), (0, 0), (90, 1), (90, 1), (90, 1)],
    (202, 2): [(20, 0), (0, 0), (35, 0), (0, 0), (61, 1), (12, 0), (30, 0)],
}
MOVER = [(2, 90, 1), (2, 30, 0), (2, 90, 1), (2, 0, 0), (1, 45, 0), (1, 90, 1), (1, 20, 0)]
FIXTURES = [
    (1, 1, 3), (1, 2, 4), (2, 1, 2), (3, 3, 1), (3, 2, 4), (4, 1, 4), (5, 2, 1), (5, 1, 3),
    (6, 2, 3), (6, 4, 1), (7, 1, 2),                     # history, to as-of 7
    (8, 1, 3), (8, 2, 4), (9, 1, 2), (9, 3, 1), (10, 2, 3),   # horizon GW8-10
]
PLAYERS = [(101, 1, "GKP", "a", None), (102, 1, "DEF", "d", 75), (103, 1, "MID", "a", 0),
           (104, 1, "FWD", "i", 0), (105, 1, "MID", "a", None), (201, 2, "MID", "n", 0),
           (202, 2, "FWD", "a", 100), (203, 2, "DEF", "a", None)]


def regression_tables() -> dict:
    pgw = [(p, club, gw, m, s) for (p, club), weeks in HISTORY.items()
           for gw, (m, s) in enumerate(weeks, start=1)]
    pgw += [(105, club, gw, m, s) for gw, (club, m, s) in enumerate(MOVER, start=1)]
    return tables(pgw, FIXTURES, PLAYERS)


# (player_id, match_id, p_appear, p_start, p_60, exp_minutes), to 6 decimals. 102's chance of
# 75 scales GW8, the next gameweek, only (decided 2026-11-23): his GW9 rows m13 and m14 were
# 0.75 times these in the first version. 203, a new signing with no history, takes the DEF
# prior (decided 2026-11-24); he was all zeros before.
EXPECTED = [
    (101, "m11", 1.0, 1.0, 1.0, 90.0),
    (102, "m11", 0.6875, 0.6875, 0.5775, 53.075),
    (103, "m11", 0.785714, 0.5, 0.5, 45.064935),
    (104, "m11", 0.0, 0.0, 0.0, 0.0),
    (105, "m11", 0.904762, 0.333333, 0.333333, 42.519481),
    (201, "m12", 0.0, 0.0, 0.0, 0.0),
    (202, "m12", 0.833766, 0.2, 0.2, 30.065299),
    (203, "m12", 0.875, 0.875, 0.7, 69.125),
    (101, "m13", 1.0, 1.0, 1.0, 90.0),
    (102, "m13", 0.916667, 0.916667, 0.77, 70.766667),
    (103, "m13", 0.785714, 0.5, 0.5, 45.064935),
    (104, "m13", 0.0, 0.0, 0.0, 0.0),
    (105, "m13", 0.904762, 0.333333, 0.333333, 42.519481),
    (201, "m13", 0.0, 0.0, 0.0, 0.0),
    (202, "m13", 0.833766, 0.2, 0.2, 30.065299),
    (203, "m13", 0.875, 0.875, 0.7, 69.125),
    (101, "m14", 0.957143, 0.9, 0.9, 82.335714),
    (102, "m14", 0.825, 0.825, 0.693, 63.69),
    (103, "m14", 0.764286, 0.45, 0.45, 41.787013),
    (104, "m14", 0.0, 0.0, 0.0, 0.0),
    (105, "m14", 0.9, 0.3, 0.3, 40.196104),
    (201, "m15", 0.0, 0.0, 0.0, 0.0),
    (202, "m15", 0.833766, 0.2, 0.2, 30.065299),
    (203, "m15", 0.875, 0.875, 0.7, 69.125),
]


def test_the_output_is_unchanged() -> None:
    out = minutes_from_tables(regression_tables(), 7, SETTINGS, PREM)
    want = pd.DataFrame(EXPECTED, columns=["player_id", "match_id", "p_appear", "p_start",
                                           "p_60", "exp_minutes"])
    pd.testing.assert_frame_equal(out.drop(columns=["team_id", "gw"]), want, atol=1e-6)
    # m13 and m14 are both GW9 (club 1's double; m13 kicks off first); club 1 is blank in GW10.
    assert out.gw.tolist() == [8] * 8 + [9] * 13 + [10] * 3
    assert out.team_id.tolist() == [1] * 5 + [2] * 3 + [1] * 5 + [2] * 3 + [1] * 5 + [2] * 3


def test_two_rows_check_by_hand() -> None:
    out = minutes_from_tables(regression_tables(), 7, SETTINGS, PREM).set_index(
        ["player_id", "match_id"])
    # 101, GW9's second fixture: start rate 1 cut by 0.1. He has never missed a start, so his
    # bench rate is the league's, 8 bench appearances in 14 single-fixture non-starts, at
    # 187 / 8 = 23.375 minutes each.
    b, mb = 8 / 14, 187 / 8
    assert out.loc[(101, "m14")].p_appear == pytest.approx(0.9 + 0.1 * b)
    assert out.loc[(101, "m14")].exp_minutes == pytest.approx(0.9 * 90 + 0.1 * b * mb)
    # 102 (DEF, chance 75): weighted starts 11/3 over 4 fixtures (GW5's double counts two).
    # P(60 | start): 2 of 7/3 weighted single-fixture starts, with the DEF prior 4/5 at k = 1.
    # Minutes given a start: 535/3 weighted minutes plus the DEF prior 79, over 10/3.
    p_start = 0.75 * (11 / 3) / 4
    assert out.loc[(102, "m11")].p_start == pytest.approx(p_start)
    assert out.loc[(102, "m11")].p_60 == pytest.approx(p_start * (2 + 0.8) / (7 / 3 + 1))
    assert out.loc[(102, "m11")].exp_minutes == pytest.approx(
        p_start * (535 / 3 + 79) / (10 / 3))
    # The chance is for GW8 only: in GW9 he starts at the unscaled rate, cut by 0.1 in m14,
    # the second fixture of club 1's double.
    assert out.loc[(102, "m13")].p_start == pytest.approx((11 / 3) / 4)
    assert out.loc[(102, "m14")].p_start == pytest.approx(0.9 * (11 / 3) / 4)
    # 203 (DEF) has no gameweek yet, so he takes the DEF prior, which here is 102's season:
    # 7 starts in 8 fixtures, 4 of 5 single-fixture starts reaching 60 at 395 / 5 minutes,
    # and no bench appearance in his one non-start.
    assert out.loc[(203, "m12")].p_start == pytest.approx(7 / 8)
    assert out.loc[(203, "m12")].p_appear == pytest.approx(7 / 8)
    assert out.loc[(203, "m12")].p_60 == pytest.approx(7 / 8 * 4 / 5)
    assert out.loc[(203, "m12")].exp_minutes == pytest.approx(7 / 8 * 395 / 5)
