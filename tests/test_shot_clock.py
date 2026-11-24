"""The shot clock rule (45+ and 90+) and the inclusive spell boundaries."""

from __future__ import annotations

import numpy as np
import pandas as pd

from fpl.shots import shot_clock
from fpl.spells import on_pitch


def clock(minute: list[int], added: list[float]) -> list[float]:
    return shot_clock(pd.Series(minute), pd.Series(added, dtype="float64")).tolist()


def test_a_plain_minute_is_its_own_clock() -> None:
    assert clock([1, 44, 46, 89, 90], [np.nan] * 5) == [1, 44, 46, 89, 90]


def test_second_half_stoppage_is_ninety_plus_the_added_time() -> None:
    assert clock([90, 90], [1, 7]) == [91, 97]


def test_first_half_stoppage_sits_between_45_and_46() -> None:
    (c,) = clock([45], [3])
    assert 45 < c < 46
    assert clock([45], [1]) == clock([45], [9])  # stoppage order is unknown, so all equal


def test_minute_45_without_added_time_stays_45() -> None:
    assert clock([45], [np.nan]) == [45]


def spells() -> pd.DataFrame:
    """A starter subbed off at 60, his replacement, a starter to the whistle, a half-time sub."""
    return pd.DataFrame({
        "player_id": [1, 2, 3, 4],
        "spell_start": [0.0, 60.0, 0.0, 46.0],
        "spell_end": [60.0, np.nan, np.nan, 70.0],
    })


def at(s: pd.DataFrame, c: float) -> list[bool]:
    return on_pitch(s.spell_start, s.spell_end, c).tolist()


def test_both_spell_ends_are_included() -> None:
    s = spells()
    assert at(s, 60.0) == [True, True, True, True]  # the swap minute: off and on both count
    assert at(s, 59.0) == [True, False, True, True]
    assert at(s, 61.0) == [False, True, True, True]


def test_a_null_end_means_on_until_the_whistle_even_after_ninety() -> None:
    assert at(spells(), 97.0) == [False, True, True, False]


def test_a_half_time_sub_is_not_on_in_first_half_stoppage_but_the_player_he_replaced_is() -> None:
    s = pd.DataFrame({"spell_start": [0.0, 46.0], "spell_end": [46.0, np.nan]})
    (stoppage,) = clock([45], [2])
    assert at(s, stoppage) == [True, False]
    assert at(s, 46.0) == [True, True]
