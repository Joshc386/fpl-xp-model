"""The shot and spell tables and their checks on the real upstream checkout.

Skipped when data/raw/upstream is not there. The counts are those at upstream `ac8be9c`
(docs/decisions.md, 2026-11-23); the 2026/27 ones are for GW1-10 and only grow.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fpl.clean import BuiltSeason, build_season
from fpl.ingest import ROOT, RawSeason, load_config, read_season, upstream_data_dir
from fpl.matchcheck import check_against_matches
from fpl.validate_spells import check_shots_and_spells

CFG = load_config(ROOT / "config" / "pipeline.yaml")
DATA = upstream_data_dir(CFG)
pytestmark = pytest.mark.skipif(
    not (DATA / "2025-2026" / "By Gameweek" / "GW38").exists(), reason="no upstream checkout"
)


SPELL = ["spell_start", "spell_end", "spell_repaired"]


def read(season: str) -> RawSeason:
    scfg = next(s for s in CFG["seasons"] if s["id"] == season)
    return read_season(
        DATA, scfg, "x", None, prem_tag=CFG["premier_league_tag"],
        offset_minutes=CFG["loader"]["deadline_offset_minutes"],
    )


@pytest.fixture(scope="module")
def built() -> dict[str, tuple[RawSeason, BuiltSeason]]:
    out = {}
    for season in ("2025-2026", "2026-2027"):
        raw = read(season)
        out[season] = (raw, build_season(raw, CFG))
    return out


def rec(b: BuiltSeason, table: str, line: str, reason: str = "") -> int:
    r = b.reconciliation
    return int(r[(r.table == table) & (r.line == line) & (r.reason == reason)].rows.iloc[0])


def test_every_check_passes_on_the_real_data_with_its_counts(built: dict) -> None:
    for season, (raw, b) in built.items():
        problems, counts = check_shots_and_spells(b.tables, CFG)
        assert problems == [], season
        against, stats = check_against_matches(b.tables, raw.matches, CFG)
        assert against == [], season
        assert stats["penalty_xg_mismatch"] == stats["shot_count_mismatch"] == 0
        assert stats["goals_mismatch"] == stats["team_xg_mismatch"] == 0
        assert 0.97 <= stats["team_xg_ratio"] <= 1.03


def test_2025_26_row_counts_and_reasons(built: dict) -> None:
    raw, b = built["2025-2026"]
    assert len(b.tables["fact_shot"]) == 9504 and len(b.tables["fact_player_spell"]) == 11490
    assert rec(b, "fact_shot", "rows_in") == 12129
    assert rec(b, "fact_shot", "dropped", "match_not_premier_league") == 2625
    for reason in ("match_has_no_kickoff_time", "match_not_complete"):
        assert rec(b, "fact_shot", "dropped", reason) == 0
    assert [rec(b, "fact_shot", "info", r) for r in
            ("player_blank", "own_goal", "shooter_not_in_player_match", "shooter_off_pitch",
             "shooter_no_minutes")] == [0, 0, 0, 4, 0]
    assert rec(b, "fact_player_spell", "dropped", "spell_start_unknown") == 2
    assert rec(b, "fact_player_spell", "dropped", "no_minutes") == 1262
    assert rec(b, "fact_player_spell", "dropped", "match_not_premier_league") == 1835
    assert [rec(b, "fact_player_spell", "info", r) for r in
            ("spell_repaired", "fpl_minutes_mismatch", "fpl_minutes_without_spell",
             "starters_over_11", "starters_under_11")] == [0, 6, 2, 0, 0]


def test_2026_27_row_counts_and_reasons(built: dict) -> None:
    raw, b = built["2026-2027"]
    assert len(b.tables["fact_shot"]) >= 2738 and len(b.tables["fact_player_spell"]) >= 3076
    assert rec(b, "fact_shot", "dropped", "match_not_premier_league") == 0  # no cup shot files
    assert rec(b, "fact_shot", "info", "player_blank") >= 314  # kept, not imputed
    assert rec(b, "fact_shot", "info", "own_goal") >= 13
    shot = b.tables["fact_shot"]
    assert shot.loc[shot.is_own_goal, "player_id"].isna().all()
    assert rec(b, "fact_player_spell", "dropped", "no_minutes") >= 909


def test_a_sent_off_player_is_repaired_on_real_rows(built: dict) -> None:
    """Player 54 of 2026/27 GW1 was sent off after 40 minutes; upstream's finish_min says 95."""
    spell = built["2026-2027"][1].tables["fact_player_spell"]
    row = spell[(spell.player_id == 54) & spell.match_id.str.contains("brighton-hove-albion-vs-as")]
    assert row[SPELL].iloc[0].tolist() == [0.0, 40.0, True]
    raw26 = built["2025-2026"][1].tables["fact_player_spell"]
    red = raw26[(raw26.player_id == 457) & raw26.match_id.str.endswith("united-vs-chelsea")]
    # an end an incident gave is never repaired: FPL's 49 minutes include stoppage time
    assert red[SPELL].iloc[0].tolist() == [0.0, 45.5, False]
    one_minute = raw26[raw26.match_id.str.endswith("everton-vs-manchester-united")
                       & (raw26.player_id == 447)]
    got = one_minute.iloc[0]  # his start is start_min: there is no "on" incident
    assert got.spell_start == 95.0 and pd.isna(got.spell_end) and not got.spell_repaired
    gone = raw26[((raw26.player_id == 345) & raw26.match_id.str.endswith("leeds-united-vs-fulham"))
                 | ((raw26.player_id == 605) & raw26.match_id.str.contains("west-ham-united-vs-s"))]
    assert gone.empty  # start_min 4 and 3 for one minute: dropped, not repaired
    aston = raw26[(raw26.player_id == 50) & raw26.match_id.str.endswith("aston-villa-vs-burnley")]
    assert aston[SPELL].iloc[0].tolist() == [67.0, 100.0, False]


def test_an_unused_substitute_has_no_spell_on_the_real_data(built: dict) -> None:
    for _, b in built.values():
        pm, spell = b.tables["fact_player_match"], b.tables["fact_player_spell"]
        unused = pm[pm.minutes == 0][["player_id", "match_id"]]
        assert len(unused) > 0
        assert len(unused.merge(spell, on=["player_id", "match_id"])) == 0
        played = pm[pm.minutes > 0].merge(
            b.tables["fact_fixture"][["match_id", "tournament"]], on="match_id")
        lost = rec(b, "fact_player_spell", "dropped", "spell_start_unknown")
        assert len(spell) == (played.tournament == "prem").sum() - lost


def test_fact_player_gw_goals_and_assists_are_fpls_own_on_the_real_data(built: dict) -> None:
    raw, b = built["2026-2027"]
    pgs = raw.player_gameweek_stats.rename(columns={"id": "player_id"})
    pgw = b.tables["fact_player_gw"].merge(
        pgs[["player_id", "gw", "goals_scored", "assists"]], on=["player_id", "gw"])
    assert len(pgw) == len(b.tables["fact_player_gw"])
    assert (pgw.fpl_goals == pgw.goals_scored).all() and (pgw.fpl_assists == pgw.assists).all()
    # FPL's assists are wider than the match stats' (243 against 179 over GW1-10) ...
    assert pgw.fpl_assists.sum() > premier(b, "assists") > 0
    # ... and in 2025/26 upstream's match stats equal FPL's exactly (942).
    old = built["2025-2026"][1]
    assert old.tables["fact_player_gw"].fpl_assists.sum() == premier(old, "assists") == 942


def premier(b: BuiltSeason, col: str) -> int:
    """The sum of a fact_player_match column over Premier League matches."""
    pm = b.tables["fact_player_match"].merge(
        b.tables["fact_fixture"][["match_id", "tournament"]], on="match_id")
    return int(pm.loc[pm.tournament == "prem", col].sum())
