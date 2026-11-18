"""The outside-source Elo check's per-match table: windows, partners, gaps and promoted clubs."""

from __future__ import annotations

import pandas as pd
from backtest.beyondelo_data import Window, window_table
from backtest.beyondelo_fit import AWAY, DRAW, HOME

from beyondelo_check_frames import PREM, beyondelo, fixtures, ratings

W = Window("scored", "2025-2026", 3, 4)
OURS = {1: 1900.0, 2: 1800.0, 3: 1750.0, 4: 1600.0}
THEIRS = {1: 2000.0, 2: 1850.0, 3: 1700.0, 4: 1650.0}


def fx() -> pd.DataFrame:
    return fixtures([("a", 2, 1, 2, 1, 0, True), ("b", 3, 1, 2, 2, 1, True),
                     ("c", 3, 3, 4, 0, 0, True), ("d", 4, 4, 1, 3, 1, True),
                     ("e", 4, 2, 3, 0, 2, True), ("f", 5, 1, 3, 1, 1, True)])


def test_a_window_holds_its_gameweeks_matches_with_both_gaps_and_the_result() -> None:
    f = fx()
    t, counts, problems = window_table(W, ratings(f, OURS), beyondelo(f, THEIRS), f, PREM)
    assert list(t.match_id) == ["b", "c", "d", "e"]
    assert list(t.result) == [HOME, DRAW, HOME, AWAY]
    assert list(t.gap_ours) == [100.0, 150.0, -300.0, 50.0]
    assert list(t.gap_beyondelo) == [150.0, 50.0, -350.0, 150.0]
    assert counts == {"matches": 4, "finished_result": 4, "our_rating": 4,
                      "beyondelo_rating": 4, "complete": 4}
    assert problems == {}


def test_a_match_is_promoted_when_either_side_is() -> None:
    f = fx()
    t, _, _ = window_table(W, ratings(f, OURS), beyondelo(f, THEIRS, promoted={4}), f, PREM)
    assert dict(zip(t.match_id, t.promoted, strict=True)) == {"b": False, "c": True,
                                                              "d": True, "e": False}


def test_a_missing_rating_row_on_either_side_is_a_missing_partner() -> None:
    f = fx()
    ours = ratings(f, OURS, drop=(("c", 4),))
    theirs = beyondelo(f, THEIRS, drop=(("e", 2),))
    t, counts, problems = window_table(W, ours, theirs, f, PREM)
    assert problems == {"our_rating": ["c"], "beyondelo_rating": ["e"]}
    assert counts["our_rating"] == 3 and counts["beyondelo_rating"] == 3
    assert counts["complete"] == 2 and list(t.match_id) == ["b", "d"]


def test_a_null_rating_or_a_rating_of_another_club_is_a_missing_partner() -> None:
    f = fx()
    ours = ratings(f, OURS)
    ours.loc[(ours.match_id == "b") & (ours.team_id == 1), "elo_before"] = float("nan")
    theirs = beyondelo(f, THEIRS)
    theirs.loc[(theirs.match_id == "d") & (theirs.team_id == 1), "team_id"] = 3
    _, _, problems = window_table(W, ours, theirs, f, PREM)
    assert problems == {"our_rating": ["b"], "beyondelo_rating": ["d"]}


def test_a_duplicated_rating_row_is_not_a_partner() -> None:
    f = fx()
    ours = ratings(f, OURS)
    ours = pd.concat([ours, ours[ours.match_id == "c"].head(1)], ignore_index=True)
    _, _, problems = window_table(W, ours, beyondelo(f, THEIRS), f, PREM)
    assert problems == {"our_rating": ["c"]}


def test_an_unfinished_match_has_no_finished_result() -> None:
    f = fx()
    f.loc[f.match_id == "d", ["home_goals", "away_goals"]] = pd.NA
    f.loc[f.match_id == "d", "finished"] = False
    _, counts, problems = window_table(W, ratings(f, OURS), beyondelo(f, THEIRS), f, PREM)
    assert problems == {"finished_result": ["d"]} and counts["finished_result"] == 3


def test_a_rated_match_missing_from_the_fixtures_has_no_finished_result() -> None:
    f = fx()
    _, counts, problems = window_table(W, ratings(f, OURS), beyondelo(f, THEIRS),
                                       f[f.match_id != "e"], PREM)
    assert problems == {"finished_result": ["e"]}
    assert counts["matches"] == 4 and counts["complete"] == 3


def test_rows_of_another_season_or_competition_are_ignored() -> None:
    f = fx()
    other = fixtures([("x", 3, 1, 2, 1, 0, True)], season="2026-2027")
    cup = fixtures([("y", 3, 3, 4, 1, 0, True)]).assign(tournament="cup")
    ours = pd.concat([ratings(f, OURS), ratings(other, OURS)], ignore_index=True)
    t, counts, problems = window_table(W, ours, beyondelo(f, THEIRS),
                                       pd.concat([f, other, cup], ignore_index=True), PREM)
    assert list(t.match_id) == ["b", "c", "d", "e"] and problems == {}
