"""The shot and spell checks that run on every read: each fails on a planted fault."""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest

from fpl.validate_spells import check_shots_and_spells
from shot_tables import frame, mini

ZERO = {"share": 0.0, "always_allowed": 0}
CAPPED = ("max_repaired", "max_fpl_minutes_mismatch", "max_fpl_minutes_without_spell",
          "max_starters_not_11", "max_shooter_off_pitch")  # shooter_no_minutes shares the last


@pytest.fixture
def strict(cfg: dict) -> dict:
    """The config with every cap at zero, so one counted row fails."""
    out = copy.deepcopy(cfg)
    for key in CAPPED:
        out["spells"][key] = dict(ZERO)
    return out


def run(tables: dict, cfg: dict) -> tuple[list[str], dict[str, int]]:
    return check_shots_and_spells(tables, cfg)


def test_the_consistent_league_passes_with_every_count_zero(strict: dict) -> None:
    problems, counts = run(mini(), strict)
    assert problems == []
    assert counts == {
        "spell_repaired": 0, "fpl_minutes_mismatch": 0, "fpl_minutes_without_spell": 0,
        "starters_over_11": 0, "starters_under_11": 0, "shooter_off_pitch": 0,
        "shooter_no_minutes": 0,
    }


def test_xg_outside_zero_to_one_fails(cfg: dict) -> None:
    t = mini()
    t["fact_shot"].loc[0, "xg"] = 1.2
    assert any("xg" in p for p in run(t, cfg)[0])


@pytest.mark.parametrize("minute", [0, 91])
def test_a_minute_outside_1_to_90_fails(cfg: dict, minute: int) -> None:
    t = mini()
    t["fact_shot"].loc[0, "minute"] = minute
    assert any("minute" in p for p in run(t, cfg)[0])


@pytest.mark.parametrize(("col", "value"), [("situation", "volley"), ("outcome", "deflected")])
def test_a_new_situation_or_outcome_fails_the_run(cfg: dict, col: str, value: str) -> None:
    t = mini()
    t["fact_shot"].loc[0, col] = value
    assert any(col in p and value in p for p in run(t, cfg)[0])


def test_a_complete_match_with_no_shot_rows_fails(cfg: dict) -> None:
    t = mini()
    t["fact_shot"] = t["fact_shot"][t["fact_shot"].match_id != "m2"]
    assert any("m2" in p and "no shot rows" in p for p in run(t, cfg)[0])


def test_a_spell_for_an_unused_substitute_fails_even_with_a_cap(cfg: dict) -> None:
    t = mini()
    extra = frame("fact_player_spell", [{
        "player_id": 113, "team_id": 1, "match_id": "m1", "spell_start": 0.0,
        "spell_end": np.nan, "spell_repaired": False}])
    t["fact_player_spell"] = pd.concat([t["fact_player_spell"], extra], ignore_index=True)
    assert any("unused substitute" in p for p in run(t, cfg)[0])


def test_a_spell_for_a_player_with_zero_fpl_minutes_fails(cfg: dict) -> None:
    t = mini()
    gw = t["fact_player_gw"]
    gw.loc[(gw.player_id == 112) & (gw.gw == 1), "minutes"] = 0
    assert any("FPL minutes 0" in p for p in run(t, cfg)[0])


def test_repaired_spells_are_counted_and_capped(cfg: dict, strict: dict) -> None:
    t = mini()
    t["fact_player_spell"].loc[0, "spell_repaired"] = True
    problems, counts = run(t, cfg)
    assert problems == [] and counts["spell_repaired"] == 1  # under the cap
    problems, counts = run(t, strict)
    assert counts["spell_repaired"] == 1 and any("spell_repaired" in p for p in problems)


def test_fpl_minutes_that_differ_from_the_spells_are_counted(strict: dict) -> None:
    t = mini()
    gw = t["fact_player_gw"]
    gw.loc[(gw.player_id == 112) & (gw.gw == 1), "minutes"] = 80  # the spell says 30
    problems, counts = run(t, strict)
    assert counts["fpl_minutes_mismatch"] == 1
    assert any("fpl_minutes_mismatch" in p for p in problems)
    gw.loc[(gw.player_id == 112) & (gw.gw == 1), "minutes"] = 32  # within 2 minutes
    assert run(t, strict)[1]["fpl_minutes_mismatch"] == 0


def test_fpl_minutes_with_no_spell_are_counted(strict: dict) -> None:
    t = mini()
    spell = t["fact_player_spell"]
    t["fact_player_spell"] = spell[~((spell.player_id == 112) & (spell.match_id == "m1"))]
    problems, counts = run(t, strict)
    assert counts["fpl_minutes_without_spell"] == 1
    assert any("fpl_minutes_without_spell" in p for p in problems)


def test_a_spell_to_93_against_90_fpl_minutes_is_clipped_at_90_and_agrees(strict: dict) -> None:
    """A starter on until 90+3 played 90 minutes by FPL's count: the spell's minutes inside 90
    are 90, not 93."""
    t = mini()
    spell = t["fact_player_spell"]
    spell.loc[(spell.player_id == 101) & (spell.match_id == "m1"), "spell_end"] = 93.0
    assert run(t, strict)[1]["fpl_minutes_mismatch"] == 0


def test_the_fpl_comparison_skips_a_gameweek_the_club_has_not_completed(strict: dict) -> None:
    """Club 2's GW2 fixture is not complete, so a mismatch in club 2's GW2 rows isn't counted."""
    t = mini()
    t["fact_fixture"].loc[t["fact_fixture"].match_id == "m2", "stats_complete"] = False
    gw = t["fact_player_gw"]
    gw.loc[(gw.player_id == 212) & (gw.gw == 2), "minutes"] = 80
    for name in ("fact_shot", "fact_player_spell", "fact_player_match"):
        t[name] = t[name][t[name].match_id == "m1"]
    problems, counts = run(t, strict)
    assert problems == [] and counts["fpl_minutes_mismatch"] == 0


def test_starters_over_and_under_eleven_are_counted_by_reason(strict: dict) -> None:
    t = mini()
    spell = t["fact_player_spell"]
    t["fact_player_spell"] = spell[~((spell.player_id == 101) & (spell.match_id == "m1"))]
    problems, counts = run(t, strict)
    assert counts["starters_under_11"] == 1 and counts["starters_over_11"] == 0
    assert any("starters_under_11" in p for p in problems)
    t = mini()
    spell = t["fact_player_spell"]
    spell.loc[(spell.player_id == 112) & (spell.match_id == "m1"), "spell_start"] = 0.0
    assert run(t, strict)[1]["starters_over_11"] == 1


def test_a_shooter_off_the_pitch_is_counted_and_the_boundary_is_inclusive(strict: dict) -> None:
    t = mini()
    shot = t["fact_shot"]
    mine = (shot.player_id == 112) & (shot.match_id == "m1")
    shot.loc[mine, "clock"] = 59.9  # before his start at 60
    problems, counts = run(t, strict)
    assert counts["shooter_off_pitch"] == 1 and any("shooter_off_pitch" in p for p in problems)
    shot.loc[mine, "clock"] = 60.0  # at his start
    assert run(t, strict)[1]["shooter_off_pitch"] == 0
    shot.loc[shot.player_id == 101, "clock"] = 97.0  # a starter to the whistle
    assert run(t, strict)[1]["shooter_off_pitch"] == 0


def test_a_blank_shooter_and_a_shooter_with_no_spell_are_not_off_the_pitch(strict: dict) -> None:
    t = mini()
    shot = t["fact_shot"]
    shot.loc[0, "player_id"] = pd.NA
    shot.loc[1, "player_id"] = 999
    assert run(t, strict)[1]["shooter_off_pitch"] == 0


def test_a_shooter_with_a_player_match_row_but_no_minutes_is_counted(strict: dict) -> None:
    """An unused substitute (13) credited with a shot: a contradiction, counted by reason."""
    t = mini()
    shot = t["fact_shot"]
    shot.loc[0, "player_id"] = 113  # club 1's unused substitute, match m1
    problems, counts = run(t, strict)
    assert counts["shooter_no_minutes"] == 1 and counts["shooter_off_pitch"] == 0
    assert any("shooter_no_minutes" in p for p in problems)


def test_a_shooter_with_no_player_match_row_at_all_is_not_counted_as_no_minutes(
    strict: dict,
) -> None:
    t = mini()
    t["fact_shot"].loc[0, "player_id"] = 999
    assert run(t, strict)[1]["shooter_no_minutes"] == 0


def test_counts_over_the_default_cap_fail(cfg: dict) -> None:
    t = mini()
    t["fact_player_spell"]["spell_repaired"] = True  # every spell repaired
    problems, counts = run(t, cfg)
    assert counts["spell_repaired"] == len(t["fact_player_spell"])
    assert any("spell_repaired" in p for p in problems)


def test_empty_tables_pass(cfg: dict) -> None:
    t = {k: v.iloc[0:0] for k, v in mini().items()}
    problems, counts = run(t, cfg)
    assert problems == [] and set(counts.values()) == {0}
