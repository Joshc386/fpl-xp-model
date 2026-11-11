"""Which matches an as-of read holds: Premier League up to g, cup matches played up to g."""

from __future__ import annotations

import pandas as pd
import pytest

from fpl.asof import deadlines, played_gw, select_matches
from helpers import match_row, matches_frame

N_GW, OFFSET = 3, 90


def schedule() -> pd.DataFrame:
    """GW1-3 Premier League matches; first kickoffs 13 Sep 10:00, 20 Sep 12:00, 27 Sep 12:00."""
    rows = [
        match_row("p1", 1.0, 2.0, snapshot_gw=1, gameweek=1, kickoff_time="2026-09-13T10:00:00"),
        match_row("p2", 3.0, 4.0, snapshot_gw=2, gameweek=2,
                  kickoff_time="2026-09-20T14:00:00+00:00"),
        match_row("p2b", 1.0, 3.0, snapshot_gw=2, gameweek=2,
                  kickoff_time="2026-09-20T12:00:00+00:00"),
        match_row("p3", 1.0, 4.0, snapshot_gw=3, gameweek=3, kickoff_time="2026-09-27T12:00:00",
                  finished=False),
    ]
    return matches_frame(rows)


def with_cup(*cups: tuple[str, int, str | None]) -> pd.DataFrame:
    """Add cup matches (id, the folder that files them, kickoff)."""
    rows = [
        match_row(mid, 1.0, 99.0, snapshot_gw=gw, gameweek=gw, tournament="efl-cup",
                  kickoff_time=k)
        for mid, gw, k in cups
    ]
    return pd.concat([schedule(), matches_frame(rows)], ignore_index=True)


def ids(df: pd.DataFrame) -> list[str]:
    return df.match_id.tolist()


def test_a_gameweeks_deadline_is_its_first_premier_league_kickoff_minus_the_offset() -> None:
    d = deadlines(schedule(), N_GW, "prem", OFFSET)
    assert d.index.tolist() == [1, 2, 3]
    assert d[1] == pd.Timestamp("2026-09-13T08:30:00Z")
    assert d[2] == pd.Timestamp("2026-09-20T10:30:00Z")  # p2b at 12:00 is the first of GW2
    assert deadlines(schedule(), N_GW, "prem", 0)[2] == pd.Timestamp("2026-09-20T12:00:00Z")


def test_a_gameweek_without_a_premier_league_kickoff_has_no_deadline_instead_of_an_error() -> None:
    m = schedule()
    m.loc[m.snapshot_gw == 2, "kickoff_time"] = None
    d = deadlines(m, N_GW, "prem", OFFSET)
    assert d.isna().tolist() == [False, True, False]
    assert deadlines(schedule(), N_GW, "nothing", OFFSET).isna().all()


@pytest.mark.parametrize(
    ("kickoff", "gw"),
    [
        ("2026-09-13T08:29:59", 0),  # before the GW1 deadline
        ("2026-09-13T08:30:00", 1),  # at the deadline counts as after it
        ("2026-09-20T10:29:59", 1),
        ("2026-09-20T10:30:00", 2),
        ("2026-09-20T11:29:59+01:00", 1),  # an offset stamp is converted to UTC
        ("2026-12-01T19:00:00", 3),
        (None, None),
    ],
)
def test_the_gameweek_played_is_the_latest_whose_deadline_is_at_or_before_kickoff(
    kickoff: str | None, gw: int | None
) -> None:
    m = with_cup(("cup", 3, kickoff))
    got = played_gw(
        pd.to_datetime(m.kickoff_time, utc=True, format="ISO8601"),
        deadlines(m, N_GW, "prem", OFFSET),
    )
    assert (pd.isna(got.iloc[-1]) if gw is None else got.iloc[-1] == gw)


@pytest.mark.parametrize(
    ("kickoff", "held"),
    [
        ("2026-09-20T10:29:59", True),
        ("2026-09-20T10:30:00", False),  # gameweek 2: after as-of 1
        ("2026-09-18T19:45:00", True),
        ("2026-09-13T08:00:00", True),  # gameweek 0, before the GW1 deadline
        (None, False),
    ],
)
def test_a_cup_match_is_held_by_the_gameweek_it_was_played_in_not_by_its_folder(
    kickoff: str | None, held: bool
) -> None:
    m = with_cup(("cup", 2, kickoff))  # filed in the GW2 folder, as upstream does
    got, left = select_matches(m, 1, N_GW, "prem", OFFSET)
    assert ("cup" in ids(got)) is held and ("cup" in ids(left)) is (not held)


def test_a_cup_matchs_gameweek_is_the_one_it_was_played_in_for_every_held_match() -> None:
    m = with_cup(("filed_late", 3, "2026-09-10T19:45:00"), ("filed_next", 2, "2026-09-18T19:45:00"))
    got, _ = select_matches(m, 2, N_GW, "prem", OFFSET)
    gw = got.set_index("match_id").gameweek
    assert gw["filed_late"] == 0 and gw["filed_next"] == 1  # not 3 and 2
    assert got.set_index("match_id").snapshot_gw["filed_late"] == 3  # the filing folder is kept
    league = got[got.tournament == "prem"]
    assert (league.gameweek == league.snapshot_gw).all()


def test_the_folder_does_not_matter_for_a_cup_match() -> None:
    m = with_cup(
        ("early_in_gw3", 3, "2026-09-10T19:45:00"), ("late_in_gw1", 1, "2026-09-25T19:45:00")
    )
    got, left = select_matches(m, 1, N_GW, "prem", OFFSET)
    assert "early_in_gw3" in ids(got) and "late_in_gw1" in ids(left)


def test_premier_league_matches_after_as_of_are_blanked_and_others_untouched() -> None:
    got, _ = select_matches(schedule(), 1, N_GW, "prem", OFFSET)
    assert ids(got) == ["p1", "p2", "p2b", "p3"]
    later = got[got.snapshot_gw > 1]
    assert not later.finished.any()
    blanked = ["home_score", "away_score", "home_expected_goals_xg", "home_team_elo"]
    assert later[blanked].isna().all().all()
    assert later.kickoff_time.notna().all() and later.home_team.notna().all()
    first = got[got.snapshot_gw == 1].iloc[0]
    assert first.finished and first.home_score == 2.0 and first.home_team_elo == 1600.0


def test_a_held_cup_match_keeps_its_result_whatever_its_folder() -> None:
    m = with_cup(("cup", 2, "2026-09-18T19:45:00"))
    got, _ = select_matches(m, 1, N_GW, "prem", OFFSET)
    cup = got[got.match_id == "cup"].iloc[0]
    assert cup.finished and cup.home_score == 2.0 and cup.home_expected_goals_xg == 1.5


def test_at_the_last_gameweek_nothing_is_left_out_not_even_a_match_without_kickoff() -> None:
    m = with_cup(("nokick", 2, None))
    got, left = select_matches(m, N_GW, N_GW, "prem", OFFSET)
    assert len(got) == len(m) and left.empty
    assert got.finished.sum() == m.finished.sum()
    assert got.set_index("match_id").gameweek["nokick"] == 2  # no kickoff: the folder stands


def test_a_missing_gameweek_does_not_raise_so_validation_can_report_the_missing_file() -> None:
    m = schedule()
    m = m[m.snapshot_gw != 2]
    got, _ = select_matches(m, 1, N_GW, "prem", OFFSET)
    assert ids(got) == ["p1", "p3"]


def test_the_input_is_not_modified() -> None:
    m = with_cup(("cup", 2, "2026-09-18T19:45:00"))
    before = m.copy()
    select_matches(m, 1, N_GW, "prem", OFFSET)
    pd.testing.assert_frame_equal(m, before)
