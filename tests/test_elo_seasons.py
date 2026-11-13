"""Seeds at season boundaries, kickoff order and the input guards (brief data rule 12)."""

from __future__ import annotations

import pandas as pd
import pytest

from elo_tables import (
    CODES_A,
    CODES_B,
    FIXTURES_A,
    FIXTURES_B,
    PREM,
    SETTINGS,
    Fixture,
    season_read,
    two_seasons,
)
from fpl.models.elo import EloError, MissingSeedError, play, prepare, run_elo, team_rows

# Season A's last-match upstream Elo per code (GW3); each differs from the club's first value.
A_LAST = {31: 1620.0, 33: 1570.0, 32: 1520.0, 34: 1430.0}
A_ID = {code: team for team, code in CODES_A.items()}


def rows(history: list) -> pd.DataFrame:
    return team_rows(run_elo(history, SETTINGS, PREM).matches)


def first_before(out: pd.DataFrame, season: str) -> dict[int, float]:
    return out[out.season == season].groupby("team_id").elo_before.first().to_dict()


def last_after(out: pd.DataFrame, season: str) -> dict[int, float]:
    return out[out.season == season].groupby("team_id").elo_after.last().to_dict()


def test_continuing_clubs_are_reseeded_from_their_last_value_of_the_previous_season() -> None:
    out = rows(two_seasons())
    want = {b: A_LAST[code] for b, code in CODES_B.items() if code in A_LAST}
    assert {b: v for b, v in first_before(out, "2026-2027").items() if b in want} == want
    assert (out.elo_before < 7000).all()  # season B's own values for them (7777) are never used


def test_the_reseed_follows_team_code_when_ids_differ() -> None:
    first = first_before(rows(two_seasons()), "2026-2027")
    # B id 1 is code 33 (A id 3, last value 1570); A id 1 (code 31) ended on 1620.
    assert first[1] == 1570.0 and first[3] == 1620.0 and first[4] == 1520.0


def test_a_null_last_match_value_carries_the_rating_not_an_earlier_value() -> None:
    a = [(3, 2, 4, 4, 1, None, 1430.0) if f[:3] == (3, 2, 4) else f for f in FIXTURES_A]
    out = rows([season_read("2025-2026", 3, CODES_A, a), two_seasons()[1]])
    carried = last_after(out, "2025-2026")[A_ID[32]]  # code 32 had 1500 and 1510 earlier
    assert first_before(out, "2026-2027")[4] == carried  # B id 4 is code 32


def test_a_third_season_without_upstream_values_carries_every_rating() -> None:
    b = FIXTURES_B[:4] + [(3, 1, 4, 1, 0, None, None), (3, 3, 2, 2, 2, None, None)]
    codes_c = {1: 32, 2: 31, 3: 35, 4: 33}
    c: list[Fixture] = [(1, 1, 2, 1, 0, None, None), (1, 3, 4, 0, 0, None, None)]
    history = [two_seasons()[0], season_read("2026-2027", 3, CODES_B, b),
               season_read("2027-2028", 1, codes_c, c)]
    out = rows(history)
    end_b = {CODES_B[t]: v for t, v in last_after(out, "2026-2027").items()}
    assert first_before(out, "2027-2028") == {t: end_b[code] for t, code in codes_c.items()}


def test_a_promoted_club_is_seeded_from_its_first_value_in_the_new_season() -> None:
    assert first_before(rows(two_seasons()), "2026-2027")[2] == 1480.0  # code 35, new to the run


def back_after_relegation(c: list[Fixture], codes_c: dict[int, int]) -> pd.DataFrame:
    """Season A, season B (code 34 relegated; GW3 values null, so B's clubs carry), then
    season C, in which code 34 comes back."""
    b = FIXTURES_B[:4] + [(3, 1, 4, 1, 0, None, None), (3, 3, 2, 2, 2, None, None)]
    return rows([two_seasons()[0], season_read("2026-2027", 3, CODES_B, b),
                 season_read("2027-2028", 1, codes_c, c)])


C_CODES = {1: 34, 2: 31, 3: 32, 4: 33}  # code 34 played season A, not season B


def test_a_club_back_after_relegation_takes_its_first_value_in_the_new_season() -> None:
    c: list[Fixture] = [(1, 1, 2, 2, 0, 1455.0, None), (1, 3, 4, 1, 1, None, None)]
    assert first_before(back_after_relegation(c, C_CODES), "2027-2028")[1] == 1455.0


def test_a_club_back_after_relegation_without_a_value_carries_its_old_rating() -> None:
    c: list[Fixture] = [(1, 1, 2, 2, 0, None, None), (1, 3, 4, 1, 1, None, None)]
    out = back_after_relegation(c, C_CODES)
    assert first_before(out, "2027-2028")[1] == last_after(out, "2025-2026")[A_ID[34]]


def test_a_club_new_to_the_run_without_a_value_raises_but_one_coming_back_does_not() -> None:
    c: list[Fixture] = [(1, 1, 2, 2, 0, None, None), (1, 3, 4, 1, 1, None, None)]
    with pytest.raises(MissingSeedError, match="Club36") as err:
        back_after_relegation(c, {1: 34, 2: 36, 3: 32, 4: 33})
    assert "Club34" not in str(err.value)


def test_play_raises_rather_than_skip_a_season_with_no_seeds() -> None:
    results, seeds = prepare(two_seasons(), PREM)
    relabelled = results.assign(season=results.season.replace("2026-2027", "2026-27"))
    with pytest.raises(EloError, match="no seeds: \\['2026-27'\\]"):
        play(relabelled, seeds, SETTINGS)


def test_reseeds_apply_from_the_season_start_before_a_club_has_played() -> None:
    codes = {1: 33, 2: 31, 3: 34, 4: 32}  # no promoted club, so as-of 0 has every seed
    schedule: list[Fixture] = [(1, 1, 2, None, None, None, None), (1, 3, 4, None, None, None, None)]
    run = run_elo([two_seasons()[0], season_read("2026-2027", 0, codes, schedule)], SETTINGS, PREM)
    assert run.ratings == A_LAST


def test_rows_out_of_kickoff_order_give_the_same_ratings() -> None:
    # Club 1 plays twice in GW2; list its later match first, as upstream does for GW33 doubles.
    double = FIXTURES_A[:2] + [(2, 1, 3, 0, 1, 1610.0, 1560.0), (2, 4, 1, 2, 2, 1440.0, 1610.0)]
    read = season_read("2025-2026", 2, CODES_A, double)
    fx = read.tables["fact_fixture"]
    shuffled = fx.iloc[[3, 0, 2, 1]].reset_index(drop=True)
    assert shuffled.kickoff_utc.iloc[0] > shuffled.kickoff_utc.iloc[2]
    swapped = read._replace(tables={**read.tables, "fact_fixture": shuffled})
    pd.testing.assert_frame_equal(rows([swapped]), rows([read]))


def test_a_league_club_missing_from_dim_team_raises() -> None:
    read = two_seasons()[0]
    teams = read.tables["dim_team"]
    broken = read._replace(tables={**read.tables, "dim_team": teams[teams.team_id != 4]})
    with pytest.raises(EloError, match="not in dim_team"):
        run_elo([broken], SETTINGS, PREM)


def test_a_finished_fixture_with_no_score_raises() -> None:
    read = two_seasons()[0]
    fx = read.tables["fact_fixture"].copy()
    fx.loc[2, "home_goals"] = pd.NA
    with pytest.raises(EloError, match="no score"):
        run_elo([read._replace(tables={**read.tables, "fact_fixture": fx})], SETTINGS, PREM)
