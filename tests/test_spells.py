"""fact_player_spell: sources, the repair rule, unused substitutes and join checks."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fpl.frames import JoinError
from fpl.ingest import read_table
from fpl.schema import check_table_schema
from fpl.spells import build_fact_player_spell as build_with_count
from helpers import blank_frame

SPELLS = Path(__file__).parent / "fixtures" / "spells"
M27 = "26-27-prem-brighton-hove-albion-vs-aston-villa"
M26 = "25-26-prem-manchester-united-vs-chelsea"
TOL = 2.0


def build(*args: object) -> pd.DataFrame:
    """The spell table only (the second result is the `spell_start_unknown` count)."""
    return build_with_count(*args)[0]


def players(tag: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The real match's fact_player_match-like rows and its raw playermatchstats rows."""
    raw = pd.read_csv(SPELLS / f"{tag}_players.csv")
    pmatch = raw[["player_id", "team_id", "match_id"]].assign(
        minutes=raw.minutes_played.astype("int64"))
    return pmatch, raw[["player_id", "match_id", "start_min", "finish_min"]]


def spells_2627() -> pd.DataFrame:
    pmatch, pms = players("2627")
    return build(pmatch, pms, None, "playermatchstats", TOL)


def spells_2526() -> pd.DataFrame:
    pmatch, pms = players("2526")
    inc = read_table(SPELLS / "2526_incidents.csv", "incidents")
    return build(pmatch, pms, inc, "incidents", TOL)


def row(df: pd.DataFrame, player: int) -> pd.Series:
    return df[df.player_id == player].iloc[0]


def test_the_table_has_the_contract_schema_for_both_sources() -> None:
    assert check_table_schema(spells_2627(), "fact_player_spell") == []
    assert check_table_schema(spells_2526(), "fact_player_spell") == []


def test_an_unused_substitute_has_no_spell() -> None:
    pmatch, _ = players("2627")
    unused = pmatch.player_id[pmatch.minutes == 0]
    assert len(unused) == 8
    out = spells_2627()
    assert not out.player_id.isin(unused).any()
    assert len(out) == (pmatch.minutes > 0).sum() == 32


def test_2627_a_starter_to_the_end_has_a_null_end_and_a_sub_keeps_his_start() -> None:
    out = spells_2627()
    full = row(out, 45)  # started, subbed off at 82
    assert (full.spell_start, full.spell_end, full.spell_repaired) == (0.0, 82.0, False)
    sub = row(out, 33)  # on at 74, finish_min 95 is the whistle
    assert sub.spell_start == 74.0 and np.isnan(sub.spell_end) and not sub.spell_repaired


def test_2627_a_sent_off_player_is_repaired_to_his_minutes_played() -> None:
    """Player 54 was sent off after 40 minutes, but upstream's finish_min is 95."""
    out = spells_2627()
    red = row(out, 54)
    assert (red.spell_start, red.spell_end, red.spell_repaired) == (0.0, 40.0, True)
    assert out.spell_repaired.sum() == 1


def test_2526_spells_come_from_the_incidents_not_from_start_and_finish() -> None:
    """The file's start_min and finish_min are all 0 or 90 here; the incidents place the subs."""
    out = spells_2526()
    off = row(out, 449)   # subbed off at 87 for 458
    on = row(out, 458)
    assert off.spell_end == 87.0 and on.spell_start == 87.0 and np.isnan(on.spell_end)
    half_time = row(out, 459)  # on at 46 for 681
    assert half_time.spell_start == 46.0
    assert row(out, 681).spell_end == 46.0
    assert row(out, 436).spell_start == 0.0 and np.isnan(row(out, 436).spell_end)


def test_2526_a_red_card_ends_the_spell() -> None:
    out = spells_2526()
    assert row(out, 220).spell_end == 5.0 and not row(out, 220).spell_repaired


def test_2526_a_first_half_stoppage_red_keeps_the_incidents_end_though_fpl_counts_49() -> None:
    """Player 457 was sent off at 45+5, so the clock says 45.5; FPL's 49 minutes include the
    stoppage time. An end an incident gave is never repaired."""
    red = row(spells_2526(), 457)
    assert (red.spell_start, red.spell_end, red.spell_repaired) == (0.0, 45.5, False)


def test_2526_has_eleven_starters_a_side_and_no_repairs() -> None:
    out = spells_2526()
    assert out[out.spell_start == 0].groupby("team_id").size().tolist() == [11, 11]
    assert out.spell_repaired.sum() == 0


def incidents(rows: list[dict]) -> pd.DataFrame:
    """Raw incidents rows of match m1 (a column left out is null)."""
    return blank_frame("incidents", [{"match_id": "m1"} | r for r in rows])


def one_match(players_: list[tuple[int, int]], inc: list[dict],
              start_mins: dict[int, float] | None = None) -> tuple:
    """(pmatch, pms, incidents) of match m1 for (player, minutes) pairs on club 1."""
    pmatch = pd.DataFrame({
        "player_id": [p for p, _ in players_], "team_id": 1, "match_id": "m1",
        "minutes": [m for _, m in players_]})
    pms = pd.DataFrame({
        "player_id": [float(p) for p, _ in players_], "match_id": "m1",
        "start_min": [(start_mins or {}).get(p, 0.0) for p, _ in players_],
        "finish_min": 0.0})
    return pmatch, pms, incidents(inc)


def test_a_second_yellow_at_70_ends_the_spell_even_where_minutes_agree() -> None:
    """The dismissal is read from the incident, not left to the repair: 71 minutes played
    agrees with the end at 70 within the tolerance, so a repair would hide a missed card."""
    pmatch, pms, inc = one_match([(1, 71), (2, 90)], [
        {"incident_type": "card", "card_type": "yellowRed", "minute": 70.0, "player_id": 1.0}])
    out = build(pmatch, pms, inc, "incidents", TOL)
    assert (row(out, 1).spell_end, row(out, 1).spell_repaired) == (70.0, False)
    assert np.isnan(row(out, 2).spell_end)


def test_a_yellow_card_alone_does_not_end_a_spell() -> None:
    pmatch, pms, inc = one_match([(1, 90)], [
        {"incident_type": "card", "card_type": "yellow", "minute": 70.0, "player_id": 1.0}])
    assert np.isnan(row(build(pmatch, pms, inc, "incidents", TOL), 1).spell_end)


def test_a_substitution_at_90_plus_3_is_on_the_incident_clock() -> None:
    pmatch, pms, inc = one_match([(1, 90), (2, 1)], [
        {"incident_type": "substitution", "minute": 90.0, "added_time": 3.0, "player_id": 1.0,
         "secondary_player_id": 2.0}])
    out = build(pmatch, pms, inc, "incidents", TOL)
    assert row(out, 1).spell_end == 93.0 and row(out, 2).spell_start == 93.0
    assert not out.spell_repaired.any()


def test_a_wrong_incident_end_is_counted_by_the_checks_not_repaired() -> None:
    pmatch, pms, inc = one_match([(1, 60)], [
        {"incident_type": "substitution", "minute": 80.0, "player_id": 1.0}])
    out = build(pmatch, pms, inc, "incidents", TOL)  # the incident says 80, FPL says 60
    assert (row(out, 1).spell_end, row(out, 1).spell_repaired) == (80.0, False)


def test_a_substitute_with_no_on_incident_takes_his_start_min_when_it_is_above_zero() -> None:
    pmatch, pms, inc = one_match([(1, 30), (2, 90)], [], {1: 60.0})
    out, unknown = build_with_count(pmatch, pms, inc, "incidents", TOL)
    assert unknown == 0 and len(out) == 2
    assert (row(out, 1).spell_start, row(out, 1).spell_repaired) == (60.0, False)
    assert np.isnan(row(out, 1).spell_end)


def test_a_start_min_that_does_not_fit_the_minutes_drops_the_spell_and_never_repairs_it() -> None:
    """Player 1: 1 minute but a start_min of 4 (90 - 4 is far from 1): dropped and counted.
    Player 2: 1 minute and a start_min of 89 fits: kept. Player 3 is 2 minutes off, within 2."""
    pmatch, pms, inc = one_match([(1, 1), (2, 1), (3, 5), (4, 90)], [], {1: 4.0, 2: 89.0, 3: 83.0})
    out, unknown = build_with_count(pmatch, pms, inc, "incidents", TOL)
    assert unknown == 1 and sorted(out.player_id) == [2, 3, 4]
    assert not out.spell_repaired.any()
    assert row(out, 2).spell_start == 89.0 and row(out, 3).spell_start == 83.0


def test_a_start_min_just_outside_the_tolerance_drops_and_the_tolerance_is_the_arguments() -> None:
    pmatch, pms, inc = one_match([(1, 5)], [], {1: 82.0})  # 90 - 82 = 8, three from 5
    assert build_with_count(pmatch, pms, inc, "incidents", 2.0)[1] == 1
    assert build_with_count(pmatch, pms, inc, "incidents", 3.0)[1] == 0


def test_a_substitute_with_no_on_incident_but_an_off_incident_takes_his_start_min() -> None:
    """On at 60 (start_min 60), off at 80: 20 minutes. He is not a starter."""
    pmatch, pms, inc = one_match([(1, 20)], [
        {"incident_type": "substitution", "minute": 80.0, "player_id": 1.0}], {1: 60.0})
    out, unknown = build_with_count(pmatch, pms, inc, "incidents", TOL)
    assert unknown == 0
    assert (row(out, 1).spell_start, row(out, 1).spell_end) == (60.0, 80.0)
    assert not row(out, 1).spell_repaired


def test_a_substitute_dismissed_with_no_on_incident_takes_his_start_min_too() -> None:
    pmatch, pms, inc = one_match([(1, 20)], [
        {"incident_type": "card", "card_type": "red", "minute": 80.0, "player_id": 1.0}], {1: 60.0})
    assert row(build(pmatch, pms, inc, "incidents", TOL), 1).spell_start == 60.0


def test_a_starter_sent_off_with_no_start_min_keeps_his_start_of_zero_and_is_not_dropped() -> None:
    """Player 457's case: 49 minutes against a dismissal at 45.5, start_min 0."""
    pmatch, pms, inc = one_match([(1, 49)], [
        {"incident_type": "card", "card_type": "yellowRed", "minute": 45.0, "added_time": 5.0,
         "player_id": 1.0}])
    out, unknown = build_with_count(pmatch, pms, inc, "incidents", TOL)
    assert unknown == 0 and len(out) == 1
    assert (row(out, 1).spell_start, row(out, 1).spell_end, row(out, 1).spell_repaired) == (
        0.0, 45.5, False)


def test_an_off_incident_substitute_whose_start_min_does_not_fit_keeps_zero() -> None:
    pmatch, pms, inc = one_match([(1, 20)], [
        {"incident_type": "substitution", "minute": 80.0, "player_id": 1.0}], {1: 30.0})
    assert row(build(pmatch, pms, inc, "incidents", TOL), 1).spell_start == 0.0


def test_a_player_with_an_on_incident_is_never_a_lost_substitute() -> None:
    """On at 88 by incident, no end, 20 minutes (a minutes mismatch): the spell is his
    incident's, kept and repaired as usual, never dropped for want of a start."""
    pmatch, pms, inc = one_match([(1, 20), (2, 90)], [
        {"incident_type": "substitution", "minute": 88.0, "player_id": 2.0,
         "secondary_player_id": 1.0}])
    out, unknown = build_with_count(pmatch, pms, inc, "incidents", TOL)
    assert unknown == 0 and sorted(out.player_id) == [1, 2]
    assert row(out, 1).spell_start == 88.0


def test_a_substitute_with_no_on_incident_and_no_start_min_is_dropped_and_counted() -> None:
    pmatch, pms, inc = one_match([(1, 1), (2, 1), (3, 90)], [])
    out, unknown = build_with_count(pmatch, pms, inc, "incidents", TOL)
    assert unknown == 2 and out.player_id.tolist() == [3]


def test_a_missing_playermatchstats_frame_leaves_such_a_substitute_unknown() -> None:
    pmatch, _, inc = one_match([(1, 1)], [])
    out, unknown = build_with_count(pmatch, None, inc, "incidents", TOL)
    assert unknown == 1 and out.empty


def test_a_starter_to_the_whistle_with_no_incidents_is_not_a_lost_substitute() -> None:
    pmatch, pms, inc = one_match([(1, 90), (2, 89)], [])
    out, unknown = build_with_count(pmatch, pms, inc, "incidents", TOL)
    assert unknown == 0 and len(out) == 2


def frame(rows: list[tuple]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(player, team, minutes, start_min, finish_min) rows of one match."""
    df = pd.DataFrame(rows, columns=["player_id", "team_id", "minutes", "start_min", "finish_min"])
    pmatch = df[["player_id", "team_id", "minutes"]].assign(match_id="m1")
    return pmatch[["player_id", "team_id", "match_id", "minutes"]], df.assign(match_id="m1")[
        ["player_id", "match_id", "start_min", "finish_min"]]


def test_the_repair_applies_beyond_the_tolerance_and_not_at_it() -> None:
    pmatch, pms = frame([(1, 1, 87, 0.0, 90.0), (2, 1, 88, 0.0, 90.0), (3, 1, 40, 0.0, 90.0)])
    out = build(pmatch, pms, None, "playermatchstats", TOL)
    got = dict(zip(out.player_id, out.spell_repaired, strict=True))
    # 90 in the clock against 88 played is within 2; 87 is 3 away; 40 is far away
    assert got == {1: True, 2: False, 3: True}
    assert row(out, 1).spell_end == 87.0 and row(out, 3).spell_end == 40.0
    assert np.isnan(row(out, 2).spell_end)


def test_a_repair_that_starts_later_adds_the_minutes_to_the_start() -> None:
    pmatch, pms = frame([(1, 1, 5, 60.0, 90.0)])  # on at 60 but FPL gives 5 minutes
    out = build(pmatch, pms, None, "playermatchstats", TOL)
    assert (out.spell_start[0], out.spell_end[0], out.spell_repaired[0]) == (60.0, 65.0, True)


def test_a_missing_start_is_read_as_zero() -> None:
    pmatch, pms = frame([(1, 1, 90, np.nan, np.nan)])
    out = build(pmatch, pms, None, "playermatchstats", TOL)
    assert (out.spell_start[0], out.spell_repaired[0]) == (0.0, False)
    assert np.isnan(out.spell_end[0])


def test_a_finish_below_ninety_is_the_end_and_ninety_or_more_is_the_whistle() -> None:
    pmatch, pms = frame([(1, 1, 89, 0.0, 89.0), (2, 1, 90, 0.0, 90.0), (3, 1, 90, 0.0, 99.0)])
    out = build(pmatch, pms, None, "playermatchstats", TOL)
    assert row(out, 1).spell_end == 89.0
    assert np.isnan(row(out, 2).spell_end) and np.isnan(row(out, 3).spell_end)


def test_a_player_with_no_playermatchstats_row_is_an_error_not_a_lost_row() -> None:
    pmatch, pms = frame([(1, 1, 90, 0.0, 90.0), (2, 1, 90, 0.0, 90.0)])
    with pytest.raises(JoinError):
        build(pmatch, pms[pms.player_id == 1], None, "playermatchstats", TOL)


def test_two_incidents_for_one_player_are_an_error_not_a_duplicate_row() -> None:
    pmatch, pms = players("2526")
    inc = read_table(SPELLS / "2526_incidents.csv", "incidents")
    subs = inc[inc.incident_type == "substitution"]
    with pytest.raises(JoinError):
        build(pmatch, pms, pd.concat([inc, subs.head(1)]), "incidents", TOL)


def test_an_unknown_spell_source_is_an_error() -> None:
    pmatch, pms = players("2627")
    with pytest.raises(ValueError, match="spell_source"):
        build(pmatch, pms, None, "lineups", TOL)
