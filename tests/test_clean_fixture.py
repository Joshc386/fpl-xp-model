"""Cleaning rules for team keys, joins and fact_fixture."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fpl.clean import build_dim_team, build_fact_fixture
from fpl.complete import complete_matches
from fpl.frames import CleanError, JoinError, checked_merge, normalise_kickoff, tenths, to_int
from fpl.ingest import RawSeason
from fpl.schema import check_table_schema
from helpers import SWAPPED, complete_all, match_row, matches_frame, teams_frame

# ---- joins ----------------------------------------------------------------------------------

def test_checked_merge_keeps_the_row_count_and_returns_the_matches() -> None:
    left = pd.DataFrame({"k": [1, 2, 3]})
    right = pd.DataFrame({"k": [1, 2], "v": ["a", "b"]})
    out = checked_merge(left, right, on="k", how="left", validate="many_to_one", name="t")
    assert len(out) == 3
    assert out.v.tolist()[:2] == ["a", "b"]


def test_checked_merge_rejects_duplicate_right_keys() -> None:
    left = pd.DataFrame({"k": [1, 2]})
    right = pd.DataFrame({"k": [1, 1], "v": ["a", "b"]})
    with pytest.raises(JoinError, match="dup"):
        checked_merge(left, right, on="k", how="left", validate="many_to_one", name="dup")


def test_checked_merge_rejects_a_changed_row_count() -> None:
    left = pd.DataFrame({"k": [1, 2, 3]})
    right = pd.DataFrame({"k": [1, 2], "v": ["a", "b"]})
    with pytest.raises(JoinError, match="rows"):
        checked_merge(left, right, on="k", how="inner", validate="many_to_one", name="inner")


# ---- dim_team and team keys -------------------------------------------------------------------

def elo_fixture(rows: list[tuple]) -> pd.DataFrame:
    """Fixture rows (kickoff, finished, home id, away id, home elo, away elo)."""
    df = pd.DataFrame(rows, columns=[
        "kickoff_utc", "finished", "home_team_id", "away_team_id",
        "home_upstream_elo", "away_upstream_elo",
    ])
    return df.astype({"home_team_id": "Int64", "away_team_id": "Int64"})


def test_dim_team_elo_is_each_clubs_latest_kickoff_value_by_time_not_row_order() -> None:
    teams = teams_frame([(1, 3), (2, 7), (3, 9)])
    fx = elo_fixture([
        ("2026-09-01T14:00:00Z", True, 1, 2, 1700.0, 1600.0),
        ("2026-08-20T14:00:00Z", True, 2, 1, 1590.0, 1690.0),  # earlier, listed later
    ])
    out = build_dim_team(teams, fx)
    assert out.upstream_elo.tolist()[:2] == [1700.0, 1600.0]  # away side counts too
    assert np.isnan(out.upstream_elo.tolist()[2])  # club 3 has no match
    assert check_table_schema(out, "dim_team") == []


def test_dim_team_elo_skips_nulls_and_unfinished_matches_and_ignores_teams_csv() -> None:
    teams = teams_frame([(1, 3), (2, 7)]).assign(elo=9999.0)  # teams.elo must not be used
    fx = elo_fixture([
        ("2026-08-20T14:00:00Z", True, 1, 2, 1650.0, 1550.0),
        ("2026-08-27T14:00:00Z", True, 1, 2, np.nan, np.nan),  # newest finished has no Elo
        ("2026-09-03T14:00:00Z", False, 1, 2, 1999.0, 1999.0),  # not finished
    ])
    assert build_dim_team(teams, fx).upstream_elo.tolist() == [1650.0, 1550.0]
    assert build_dim_team(teams, fx.iloc[0:0]).upstream_elo.isna().all()


def test_match_teams_map_through_team_code_not_team_id() -> None:
    m = matches_frame([match_row("a", home=3.0, away=7.0)])
    out, _ = build_fact_fixture(m, SWAPPED, "2026-2027", "prem", complete_all(m))
    # code 3 is team id 1 and code 7 is team id 2; ids 3 and 7 would be other clubs.
    assert out.home_team_id.tolist() == [1]
    assert out.away_team_id.tolist() == [2]


def test_real_sample_opener_is_arsenal_v_coventry_not_bournemouth_v_everton(
    raw_2627: RawSeason,
) -> None:
    fx, _ = build_fact_fixture(
        raw_2627.matches, raw_2627.teams, "2026-2027", "prem", complete_matches(
            raw_2627.matches, raw_2627.playermatchstats, raw_2627.players, raw_2627.teams
        ),
    )
    teams = build_dim_team(raw_2627.teams, fx).set_index("team_id").name
    opener = fx[fx.match_id == "26-27-prem-arsenal-vs-coventry-city"].iloc[0]
    assert teams[opener.home_team_id] == "Arsenal"
    assert teams[opener.away_team_id] == "Coventry City"


def test_non_premier_league_clubs_get_a_null_team_id() -> None:
    m = matches_frame([match_row("cup", home=np.nan, away=3.0, tournament="efl-cup")])
    out, _ = build_fact_fixture(m, SWAPPED, "2026-2027", "prem", complete_all(m))
    assert out.home_team_id.isna().all()
    assert out.away_team_id.tolist() == [1]


def test_a_premier_league_match_with_an_unmapped_team_is_an_error() -> None:
    m = matches_frame([match_row("a", home=99.0, away=3.0)])
    with pytest.raises(CleanError, match="team"):
        build_fact_fixture(m, SWAPPED, "2026-2027", "prem", complete_all(m))


# ---- fact_fixture -----------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-08-21T19:00:00", "2026-08-21T19:00:00Z"),
        ("2025-08-16T16:30:00+00:00", "2025-08-16T16:30:00Z"),
        ("2025-08-16T16:30:00+01:00", "2025-08-16T15:30:00Z"),
    ],
)
def test_kickoff_is_normalised_to_utc_iso_8601_with_z(raw: str, expected: str) -> None:
    assert normalise_kickoff(pd.Series([raw])).tolist() == [expected]


def test_finished_keeps_the_score_and_complete_keeps_the_xg() -> None:
    m = matches_frame([
        match_row("ok", 3.0, 7.0),
        match_row("live", 3.0, 7.0, finished=False, home_score=0.0, away_score=0.0),
        match_row("incomplete", 1.0, 7.0),
    ])
    complete = pd.Series([True, False, False])
    out, dropped = build_fact_fixture(m, SWAPPED, "2026-2027", "prem", complete)
    assert len(out) == 3 and dropped["no_kickoff_time"] == 0
    assert out.finished.tolist() == [True, False, True]
    assert out.stats_complete.tolist() == [True, False, False]
    goals, xg = ["home_goals", "away_goals"], ["home_xg", "away_xg", "home_npxg", "away_npxg"]
    # a part-played score on an unfinished match is nulled
    assert out.loc[[0, 2], goals].notna().all().all()
    assert out.loc[1, goals].isna().all()
    assert out.loc[0, xg].notna().all()
    assert out.loc[1:, xg].isna().all().all()
    assert check_table_schema(out, "fact_fixture") == []


def test_fact_fixture_column_mapping_and_upstream_elo_passthrough() -> None:
    m = matches_frame([match_row("a", 3.0, 7.0, home_team_elo=np.nan)])
    out, _ = build_fact_fixture(m, SWAPPED, "2026-2027", "prem", complete_all(m))
    row = out.iloc[0]
    assert (row.home_xg, row.away_xg, row.home_npxg, row.away_npxg) == (1.5, 0.7, 1.2, 0.7)
    assert (row.home_goals, row.away_goals) == (2, 1)
    assert np.isnan(row.home_upstream_elo)
    assert row.away_upstream_elo == 1500.0
    assert row.season == "2026-2027" and row.gw == 1


def test_matches_with_no_kickoff_time_are_dropped_and_counted() -> None:
    m = matches_frame([
        match_row("ok", 3.0, 7.0),
        match_row("placeholder", np.nan, 7.0, tournament="efl-cup", kickoff_time=None,
                  finished=False),
    ])
    out, dropped = build_fact_fixture(m, SWAPPED, "2026-2027", "prem", complete_all(m))
    assert out.match_id.tolist() == ["ok"]
    assert dropped == {"no_kickoff_time": 1}




# ---- helpers -------------------------------------------------------------------------------

def test_to_int_rejects_nulls_unless_nullable() -> None:
    with pytest.raises(CleanError, match="null"):
        to_int(pd.Series([1.0, np.nan]), "x")
    assert to_int(pd.Series([1.0, np.nan]), "x", nullable=True).dtype == "Int64"


def test_tenths_rounds_pounds_millions_to_integer_tenths() -> None:
    out = tenths(pd.Series([15.8, 4.5, 3.9]), "now_cost")
    assert out.tolist() == [158, 45, 39]
    assert out.dtype == "int64"


def test_upstream_elo_is_kept_for_premier_league_rows_and_null_on_cup_rows() -> None:
    m = matches_frame([
        match_row("league", 3.0, 7.0),
        match_row("cup", 3.0, 99.0, tournament="efl-cup", home_team_elo=1871.97,
                  away_team_elo=1500.0),
    ])
    out, _ = build_fact_fixture(m, SWAPPED, "2025-2026", "prem", complete_all(m))
    league, cup = out.set_index("match_id").loc["league"], out.set_index("match_id").loc["cup"]
    assert (league.home_upstream_elo, league.away_upstream_elo) == (1600.0, 1500.0)
    assert pd.isna(cup.home_upstream_elo) and pd.isna(cup.away_upstream_elo)
    # So a club's dim_team Elo can only come from its league kickoffs.
    dim = build_dim_team(SWAPPED, out).set_index("team_id").upstream_elo
    assert dim[1] == 1600.0 and dim[2] == 1500.0
