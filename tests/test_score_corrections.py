"""Brief data rule 16: cited score corrections applied to fact_fixture."""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from fpl.corrections import apply_score_corrections
from fpl.frames import CleanError

MID = "25-26-prem-liverpool-vs-manchester-united"
SEASON = "2025-2026"
ENTRY = {
    "match_id": MID, "season": SEASON, "upstream": [0, 1], "corrected": [1, 2],
    "source": "test citation",
}


def fixture(finished: bool = True, goals: tuple = (0, 1), gw: int = 8) -> pd.DataFrame:
    """A three-row fact_fixture stand-in holding the listed match."""
    return pd.DataFrame({
        "match_id": ["a", MID, "b"], "gw": [7, gw, 9], "finished": [True, finished, True],
        "home_goals": pd.array([2, goals[0], 3], dtype="Int64"),
        "away_goals": pd.array([2, goals[1], 0], dtype="Int64"),
        "home_xg": [1.1, 0.4, 2.0],
    })


def test_correction_replaces_the_goals_of_the_listed_match() -> None:
    out = apply_score_corrections(fixture(), [ENTRY], SEASON)
    row = out[out.match_id == MID].iloc[0]
    assert (row.home_goals, row.away_goals) == (1, 2)
    assert str(out.home_goals.dtype) == "Int64"


def test_every_other_row_and_column_is_untouched() -> None:
    before = fixture()
    out = apply_score_corrections(before, [ENTRY], SEASON)
    pd.testing.assert_frame_equal(
        out.drop(columns=["home_goals", "away_goals"]),
        before.drop(columns=["home_goals", "away_goals"]),
    )
    other = out.match_id != MID
    pd.testing.assert_frame_equal(out[other], before[other])
    assert before.loc[1, "home_goals"] == 0  # the input is not mutated


def test_each_correction_is_logged_at_info(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="fpl.corrections"):
        apply_score_corrections(fixture(), [ENTRY], SEASON)
    assert MID in caplog.text and "0-1" in caplog.text and "1-2" in caplog.text


def test_an_upstream_score_that_differs_fails_and_says_to_update_the_entry() -> None:
    with pytest.raises(CleanError, match=MID) as err:
        apply_score_corrections(fixture(goals=(1, 2)), [ENTRY], SEASON)
    assert "remove or update" in str(err.value)


def test_a_listed_match_missing_from_the_fixtures_fails() -> None:
    with pytest.raises(CleanError, match=MID):
        apply_score_corrections(fixture().iloc[[0, 2]], [ENTRY], SEASON)


def test_a_listed_match_not_finished_fails() -> None:
    nulls = fixture(finished=False)
    nulls["home_goals"] = pd.array([2, None, 3], dtype="Int64")
    nulls["away_goals"] = pd.array([2, None, 0], dtype="Int64")
    with pytest.raises(CleanError, match="not finished"):
        apply_score_corrections(nulls, [ENTRY], SEASON)


def test_an_as_of_read_before_the_match_leaves_it_alone() -> None:
    blank = fixture(finished=False)
    blank["home_goals"] = pd.array([2, None, 3], dtype="Int64")
    out = apply_score_corrections(blank, [ENTRY], SEASON, as_of_gw=7)
    assert out.home_goals.isna().tolist() == [False, True, False]
    with pytest.raises(CleanError, match="not finished"):
        apply_score_corrections(blank, [ENTRY], SEASON, as_of_gw=8)


def test_an_as_of_read_after_the_match_still_corrects_and_checks() -> None:
    out = apply_score_corrections(fixture(), [ENTRY], SEASON, as_of_gw=20)
    assert out.loc[1, "home_goals"] == 1
    with pytest.raises(CleanError, match="remove or update"):
        apply_score_corrections(fixture(goals=(1, 2)), [ENTRY], SEASON, as_of_gw=20)


def test_an_empty_list_is_a_no_op() -> None:
    before = fixture()
    pd.testing.assert_frame_equal(apply_score_corrections(before, [], SEASON), before)


def test_an_entry_for_the_other_season_is_ignored() -> None:
    other = {**ENTRY, "season": "2026-2027"}
    before = fixture(goals=(5, 5))  # would fail the upstream check if it were applied
    pd.testing.assert_frame_equal(apply_score_corrections(before, [other], SEASON), before)


@pytest.mark.parametrize("goals", [(0, 2), (1, 1), (1, 3), (2, 1)])
def test_a_one_sided_upstream_mismatch_fails(goals: tuple) -> None:
    with pytest.raises(CleanError, match="remove or update") as err:
        apply_score_corrections(fixture(goals=goals), [ENTRY], SEASON)
    assert f"{goals[0]}-{goals[1]}" in str(err.value)
    assert "np.int64" not in str(err.value)
