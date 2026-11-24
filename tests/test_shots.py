"""fact_shot: the club, the shooter, own goals, blanks, the clock and the join row counts."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from fpl.frames import JoinError
from fpl.ingest import read_table
from fpl.schema import check_table_schema
from fpl.shots import build_fact_shot
from fpl.validate import ValidationError

SPELLS = Path(__file__).parent / "fixtures" / "spells"
M27 = "26-27-prem-brighton-hove-albion-vs-aston-villa"
M26 = "25-26-prem-manchester-united-vs-chelsea"


def case(tag: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(raw shots, a fact_fixture-like row, fact_player_match-like rows) of a real match."""
    shots = read_table(SPELLS / f"{tag}_shots.csv", "shots")
    match = pd.read_csv(SPELLS / f"{tag}_match.csv")
    teams = pd.read_csv(SPELLS / f"{tag}_teams.csv").set_index("code").id
    fixture = pd.DataFrame({
        "match_id": match.match_id, "tournament": "prem", "stats_complete": True,
        "home_team_id": match.home_team.map(teams).astype("int64"),
        "away_team_id": match.away_team.map(teams).astype("int64"),
    })
    pm = pd.read_csv(SPELLS / f"{tag}_players.csv")
    pmatch = pm[["player_id", "team_id", "match_id"]].assign(minutes=pm.minutes_played)
    return shots, fixture, pmatch


def build(tag: str = "2627") -> tuple[pd.DataFrame, dict, dict]:
    shots, fixture, pmatch = case(tag)
    return build_fact_shot(shots, fixture, pmatch, "prem")


def test_the_table_has_the_contract_schema_and_every_shot_of_the_match() -> None:
    shots, _, _ = case("2627")
    out, dropped, _ = build()
    assert check_table_schema(out, "fact_shot") == []
    assert len(out) == len(shots) == 28
    assert sum(dropped.values()) == 0
    assert not out.duplicated(["match_id", "shot_index"]).any()


def test_the_shots_club_is_the_home_or_away_team_by_is_home() -> None:
    shots, fixture, _ = case("2627")
    out, _, _ = build()
    merged = shots.merge(out, on=["match_id", "shot_index"])
    home, away = fixture.home_team_id[0], fixture.away_team_id[0]
    assert (merged.team_id == merged.is_home.map({True: home, False: away})).all()


def test_the_clock_places_stoppage_time_shots() -> None:
    merged = pd.concat([
        case(tag)[0].merge(build(tag)[0], on=["match_id", "shot_index"], suffixes=("_raw", ""))
        for tag in ("2627", "2526")
    ])
    ninety_plus = merged[(merged.minute == 90) & merged.added_time_raw.notna()]
    first_half = merged[(merged.minute == 45) & merged.added_time_raw.notna()]
    assert len(ninety_plus) >= 1 and len(first_half) >= 1
    assert (ninety_plus.clock == 90 + ninety_plus.added_time_raw).all()
    assert (first_half.clock == 45.5).all()


def test_penalty_shots_are_flagged_from_the_situation() -> None:
    shots, _, _ = case("2526")
    out, _, _ = build("2526")
    pens = shots.situation == "penalty"
    assert out.is_penalty.sum() == pens.sum()


def test_blank_shooters_are_kept_with_a_null_player_and_counted() -> None:
    shots, _, _ = case("2627")
    out, _, counted = build()
    blanks = shots.player_id.isna()
    assert blanks.sum() >= 1
    assert counted["player_blank"] == blanks.sum()
    assert out.player_id.isna().sum() >= blanks.sum()
    assert len(out) == len(shots)


def test_an_own_goal_is_flagged_and_loses_its_shooter() -> None:
    """Player 37 (Villa) is filed as a Brighton goal at minute 8: the shot's club is the side
    that benefits."""
    shots, _, _ = case("2627")
    out, _, counted = build()
    raw = shots[(shots.player_id == 37) & (shots.minute == 8)]
    assert len(raw) == 1
    row = out.merge(raw[["match_id", "shot_index"]]).iloc[0]
    assert row.is_own_goal and pd.isna(row.player_id) and row.outcome == "goal"
    assert counted["own_goal"] == out.is_own_goal.sum() == 1
    assert out.loc[~out.is_own_goal & out.player_id.notna(), "player_id"].gt(0).all()


def test_a_shooter_with_no_player_match_row_is_kept_and_counted() -> None:
    shots, fixture, pmatch = case("2627")
    some = shots.player_id.dropna().iloc[0]
    out, _, counted = build_fact_shot(shots, fixture, pmatch[pmatch.player_id != some], "prem")
    n = int((shots.player_id == some).sum())
    assert counted["shooter_not_in_player_match"] == n and len(out) == len(shots)
    assert (out.player_id == some).sum() == n  # his id is kept


def test_an_ownGoal_outcome_with_the_shooter_on_the_clubs_side_is_not_an_own_goal() -> None:
    shots, fixture, pmatch = case("2526")
    odd = shots.assign(outcome=shots.outcome.where(shots.index != 0, "ownGoal"))
    out, _, counted = build_fact_shot(odd, fixture, pmatch, "prem")
    assert counted["own_goal"] == 0
    assert (out.outcome == "ownGoal").sum() == 1 and out.is_own_goal.sum() == 0


def test_cup_incomplete_and_unknown_matches_are_dropped_and_counted_by_reason() -> None:
    shots, fixture, pmatch = case("2627")
    cup = shots.head(3).assign(match_id="cup-1")
    todo = shots.head(2).assign(match_id="prem-todo")
    nokick = shots.head(5).assign(match_id="no-kickoff")
    extra = pd.DataFrame({
        "match_id": ["cup-1", "prem-todo"], "tournament": ["efl-cup", "prem"],
        "stats_complete": [True, False],
        "home_team_id": [1, 1], "away_team_id": [pd.NA, 2],
    })
    every = pd.concat([shots, cup, todo, nokick], ignore_index=True)
    out, dropped, _ = build_fact_shot(every, pd.concat([fixture, extra], ignore_index=True),
                                      pmatch, "prem")
    assert dropped == {"match_has_no_kickoff_time": 5, "match_not_premier_league": 3,
                       "match_not_complete": 2}
    assert len(out) == len(shots) and set(out.match_id) == {M27}
    assert len(every) - sum(dropped.values()) == len(out)  # rows in - dropped = rows out


def test_a_duplicate_fixture_or_player_match_row_is_a_join_error_not_a_duplicate_shot() -> None:
    shots, fixture, pmatch = case("2627")
    with pytest.raises(JoinError):
        build_fact_shot(shots, pd.concat([fixture, fixture]), pmatch, "prem")
    with pytest.raises(JoinError):
        build_fact_shot(shots, fixture, pd.concat([pmatch, pmatch.head(30)]), "prem")


def test_a_blank_is_home_is_a_validation_error_not_a_raw_value_error() -> None:
    shots, fixture, pmatch = case("2627")
    shots["is_home"] = shots.is_home.astype("boolean")
    shots.loc[3, "is_home"] = pd.NA
    with pytest.raises(ValidationError, match="is_home"):
        build_fact_shot(shots, fixture, pmatch, "prem")


def test_a_blank_is_home_on_a_dropped_cup_shot_is_not_an_error() -> None:
    shots, fixture, pmatch = case("2627")
    cup = shots.head(1).assign(match_id="cup-1", is_home=pd.NA)
    cup["is_home"] = cup.is_home.astype("boolean")
    extra = pd.DataFrame({"match_id": ["cup-1"], "tournament": ["efl-cup"],
                          "stats_complete": [True], "home_team_id": [1],
                          "away_team_id": [pd.NA]})
    out, dropped, _ = build_fact_shot(pd.concat([shots, cup]),
                                      pd.concat([fixture, extra], ignore_index=True), pmatch,
                                      "prem")
    assert dropped["match_not_premier_league"] == 1 and len(out) == len(shots)
