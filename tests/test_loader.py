"""The point-in-time loader on the synthetic season: leakage, consistency, modes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

import synth
from conftest import read_sample
from fpl.clean import build_season
from fpl.features import load_as_of
from fpl.overlay import OVERLAID
from fpl.schema import PROCESSED_SCHEMA, check_table_schema
from leakage import PREM, assert_no_leakage

SEASON = synth.SEASON
ALL_GW = list(range(synth.N_GW + 1))
ELO = ["home_upstream_elo", "away_upstream_elo"]
SCFG = {"id": SEASON, "gameweeks": synth.N_GW, "tackles_column": "tackles"}


@pytest.fixture(scope="module")
def env(synth_upstream: tuple[Path, dict], synth_load: Callable) -> dict:
    """The synthetic config, the full-season build to compare against, and the memoised loader."""
    root, scfg = synth_upstream
    full = build_season(read_sample(root / "data", SCFG), scfg).tables
    return {"cfg": scfg, "full": full, "load": synth_load}


def load(env: dict, as_of: int, mode: str = "backtest") -> dict[str, pd.DataFrame]:
    return env["load"](as_of, mode)


def check_no_leakage(env: dict, as_of: int, mode: str) -> None:
    tables = load(env, as_of, mode)
    assert_no_leakage(tables, as_of, env["full"]["fact_fixture"])
    for name, df in tables.items():
        assert check_table_schema(df, name) == [], name
    fx = tables["fact_fixture"]
    played = fx[(fx.tournament == PREM) & (fx.gw <= as_of)]
    assert played.finished.all()  # the played gameweeks keep their results


@pytest.mark.parametrize("as_of", ALL_GW)
def test_no_result_xg_elo_or_player_row_from_a_later_gameweek(env: dict, as_of: int) -> None:
    check_no_leakage(env, as_of, "backtest")


@pytest.mark.parametrize("as_of", [0, 1, 7, 20, 37, 38])
def test_live_mode_leaks_nothing_either(env: dict, as_of: int) -> None:
    check_no_leakage(env, as_of, "live")


def test_the_full_season_really_holds_results_in_the_folders_after_as_of(env: dict) -> None:
    # Without this the leakage tests above would pass vacuously.
    full = env["full"]["fact_fixture"]
    later = full[(full.gw > 5) & (full.tournament == PREM)]
    assert later.finished.all()
    assert later[["home_goals", "home_xg", "home_upstream_elo"]].notna().all().all()
    assert env["full"]["fact_player_gw"].gw.max() == synth.N_GW
    assert set(full.match_id[full.tournament != PREM]) == {"cup-10", "cup-late"}


def cup_ids(tables: dict) -> set[str]:
    fx = tables["fact_fixture"]
    return set(fx.match_id[fx.tournament != PREM])


@pytest.mark.parametrize(("as_of", "held"), [
    (0, set()), (1, set()), (2, {"cup-late"}), (8, {"cup-late"}),
    (9, {"cup-late", "cup-10"}), (10, {"cup-late", "cup-10"}), (38, {"cup-late", "cup-10"}),
])
def test_cup_matches_are_held_by_kickoff_whichever_folder_has_them(
    env: dict, as_of: int, held: set[str]
) -> None:
    # cup-10 is in the GW10 folder but was played in GW9, so as-of 9 holds it. cup-late is in
    # the GW25 folder but was played in GW2.
    assert cup_ids(load(env, as_of)) == held


def test_a_cup_matchs_gw_and_player_clubs_are_those_of_the_gameweek_it_was_played_in(
    env: dict,
) -> None:
    t = load(env, 9)
    pm = t["fact_player_match"]
    cup10, late = pm[pm.match_id == "cup-10"], pm[pm.match_id == "cup-late"]
    assert cup10.player_id.tolist() == [1, 2] and (cup10.team_id == 1).all()
    # cup-late is filed in the GW25 folder, whose snapshot has the mover at club 3 (not in the
    # match); the GW2 snapshot, where it was played, has him at club 1.
    assert late.player_id.tolist() == [1, 2] and (late.team_id == 1).all()
    fx = t["fact_fixture"].set_index("match_id")
    assert fx.loc["cup-10", ["gw", "finished", "stats_complete"]].tolist() == [9, True, True]
    assert fx.loc["cup-late", "gw"] == 2  # not the folder, 25
    assert fx.loc[["cup-10", "cup-late"], ELO].isna().all().all()
    assert (t["dim_team"].upstream_elo < 9000).all()  # the cups' poisoned Elo is nowhere


@pytest.mark.parametrize("as_of", [0, 1, 4, 5, 6, 7, 19, 20, 37, 38])
def test_as_of_rows_equal_the_full_builds_rows_for_what_the_read_holds(
    env: dict, as_of: int
) -> None:
    tables, full = load(env, as_of), env["full"]
    fx, full_fx = tables["fact_fixture"], full["fact_fixture"]
    shown = fx[~((fx.tournament == PREM) & (fx.gw > as_of))]
    want_fx = full_fx[full_fx.match_id.isin(shown.match_id)]
    pd.testing.assert_frame_equal(shown.reset_index(drop=True), want_fx.reset_index(drop=True))
    pm = full["fact_player_match"]
    want_pm = pm[pm.match_id.isin(shown.match_id)]
    pd.testing.assert_frame_equal(
        tables["fact_player_match"].reset_index(drop=True), want_pm.reset_index(drop=True)
    )
    pgw = full["fact_player_gw"]
    pd.testing.assert_frame_equal(
        tables["fact_player_gw"].reset_index(drop=True),
        pgw[pgw.gw <= as_of].reset_index(drop=True),
    )


def test_later_fixtures_keep_their_gameweek_kickoff_and_clubs(env: dict) -> None:
    got = load(env, 3)["fact_fixture"].set_index("match_id")
    full = env["full"]["fact_fixture"].set_index("match_id").loc[got.index]
    cols = ["gw", "kickoff_utc", "tournament", "home_team_id", "away_team_id", "season"]
    pd.testing.assert_frame_equal(got[cols].sort_index(), full[cols].sort_index())


@pytest.mark.parametrize("as_of", [1, 12, 19, 20, 38])
def test_snapshot_fields_come_from_the_as_of_folder(env: dict, as_of: int) -> None:
    t = load(env, as_of)
    dim = t["dim_player"].set_index("player_id")
    assert dim.price_tenths.to_dict() == {p: 50 + p + as_of for p in synth.PLAYER_CLUB}
    want_ep = {p: round(as_of + p / 10, 6) for p in synth.PLAYER_CLUB}
    assert dim.ep_next.round(6).to_dict() == want_ep
    assert dim.team_id.to_dict() == {p: synth.club(p, as_of) for p in synth.PLAYER_CLUB}
    assert (dim.status == "a").all() and dim.loc[3, "news"] == "Knock"


@pytest.mark.parametrize(("as_of", "want"), [
    (0, {}),
    (1, {1: 1511.0, 2: 1521.0, 3: 1531.0, 4: 1541.0}),
    (5, {1: 1515.0, 2: 1524.0, 3: 1535.0, 4: 1544.0}),  # clubs 2 and 4 are blank in GW5
])
def test_team_elo_is_the_latest_kickoff_value_in_the_read(
    env: dict, as_of: int, want: dict
) -> None:
    elo = load(env, as_of)["dim_team"].set_index("team_id").upstream_elo
    assert elo.dropna().to_dict() == want
    assert elo.isna().sum() == 4 - len(want)


def test_gameweek_zero_has_the_clubs_and_the_schedule_but_nothing_played(env: dict) -> None:
    t = load(env, 0)
    assert len(t["dim_team"]) == 4 and t["dim_team"].upstream_elo.isna().all()
    assert t["dim_player"].empty and t["fact_player_gw"].empty and t["fact_player_match"].empty
    assert len(t["fact_fixture"]) == 76 and not t["fact_fixture"].finished.any()


def test_fact_player_gw_carries_the_club_of_each_gameweek(env: dict) -> None:
    pgw = load(env, 25)["fact_player_gw"]
    want = [synth.club(p, g) for p, g in zip(pgw.player_id, pgw.gw, strict=True)]
    assert pgw.team_id.tolist() == want
    assert set(pgw[(pgw.player_id == synth.MOVER) & (pgw.gw < synth.MOVE_GW)].team_id) == {1}
    assert set(pgw[(pgw.player_id == synth.MOVER) & (pgw.gw >= synth.MOVE_GW)].team_id) == {3}


@pytest.mark.parametrize("as_of", [0, 1, 7, 20, 38])
def test_the_modes_differ_only_in_the_overlaid_fields(env: dict, as_of: int) -> None:
    back, live = load(env, as_of), load(env, as_of, "live")
    assert back.keys() == live.keys() == PROCESSED_SCHEMA.keys()
    for name in back:
        if name == "dim_player":
            continue
        pd.testing.assert_frame_equal(back[name], live[name])
    a, b = back["dim_player"], live["dim_player"]
    pd.testing.assert_frame_equal(a.drop(columns=OVERLAID), b.drop(columns=OVERLAID))
    if as_of:
        assert (b.status == "i").all() and (b.news == "Poison").all()
        assert (b.chance_next == 0).all() and (b.price_tenths == 99).all()
        assert (a.status == "a").all() and (a.price_tenths != 99).all()


@pytest.mark.parametrize(("args", "text"), [
    ((SEASON, 1, "paper"), "mode"),
    (("2031-2032", 1, "backtest"), "season"),
    ((SEASON, -1, "backtest"), "as_of_gw"),
    ((SEASON, 39, "live"), "as_of_gw"),
])
def test_bad_arguments_are_rejected(env: dict, args: tuple, text: str) -> None:
    with pytest.raises(ValueError, match=text):
        load_as_of(*args, cfg=env["cfg"])
