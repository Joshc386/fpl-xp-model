"""The completeness check replaces upstream's processing flags."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from fpl.complete import complete_matches
from helpers import SWAPPED, match_row, matches_frame, player_row, players_frame, pms_frame, pms_row

SRC = Path(__file__).resolve().parents[1] / "src" / "fpl"


def check(matches: list[dict], pms: list[dict], players: list[dict] | None = None) -> list[bool]:
    """Completeness of each match, with club 3 = players 10-11 and club 7 = players 12-13."""
    players = players or [
        player_row(10, 3), player_row(11, 3), player_row(12, 7), player_row(13, 7),
    ]
    out = complete_matches(
        matches_frame(matches), pms_frame(pms), players_frame(players), SWAPPED
    )
    return out.tolist()


def both_clubs(match_id: str) -> list[dict]:
    return [pms_row(10, match_id, 90.0), pms_row(12, match_id, 90.0)]


def test_a_finished_match_with_xg_and_rows_for_both_clubs_is_complete() -> None:
    assert check([match_row("m", 3.0, 7.0)], both_clubs("m")) == [True]


def test_the_upstream_flags_are_not_needed_to_be_complete() -> None:
    # Real GW37-38 2025/26 matches look like this: finished, full data, flags left false.
    m = match_row("m", 3.0, 7.0)
    m["stats_processed"] = False
    m["player_stats_processed"] = False
    assert check([m], both_clubs("m")) == [True]


def test_an_unfinished_match_is_not_complete_even_with_xg_and_rows() -> None:
    assert check([match_row("m", 3.0, 7.0, finished=False)], both_clubs("m")) == [False]


def test_a_finished_match_missing_a_team_xg_is_not_complete() -> None:
    for col in ("home_expected_goals_xg", "away_expected_goals_xg"):
        m = match_row("m", 3.0, 7.0, **{col: np.nan})
        assert check([m], both_clubs("m")) == [False], col


def test_a_finished_match_with_no_rows_for_one_premier_league_club_is_not_complete() -> None:
    assert check([match_row("m", 3.0, 7.0)], [pms_row(10, "m", 90.0)]) == [False]
    assert check([match_row("m", 3.0, 7.0)], []) == [False]


def test_a_cup_match_against_a_club_outside_the_premier_league_needs_only_our_club() -> None:
    cup = match_row("cup", 3.0, np.nan, tournament="efl-cup")
    assert check([cup], [pms_row(10, "cup", 90.0)]) == [True]
    assert check([cup], []) == [False]


def test_rows_are_attributed_to_clubs_by_that_gameweeks_snapshot() -> None:
    players = [player_row(10, 7), player_row(11, 7), player_row(12, 7), player_row(13, 7)]
    # player 10 now plays for club 7, so nobody in the sample represents club 3
    assert check([match_row("m", 3.0, 7.0)], both_clubs("m"), players) == [False]


def test_each_match_is_judged_on_its_own_rows() -> None:
    matches = [match_row("a", 3.0, 7.0), match_row("b", 3.0, 7.0)]
    assert check(matches, both_clubs("a")) == [True, False]


def test_the_code_never_reads_upstreams_processing_flags() -> None:
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "stats_processed" not in text, path
