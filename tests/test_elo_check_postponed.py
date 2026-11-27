"""`run_check`'s refit wiring, end to end: a wholly postponed gameweek with a cup tie kept.

The synthetic season is rewritten with GW18's two league matches moved to GW30 and an EFL Cup
tie played in GW18, so GW18 has no Premier League fixture (the loader allows that) but does
have a finished match. Between the goals reads at as-of 17 and 18 the fitting pool is
identical, so the honest model's coefficients must not move, and the pair must pass.
"""

from __future__ import annotations

from unittest import mock

import backtest.elo_check
import pandas as pd
import pytest
from backtest.elo_check import Models, run_check
from backtest.elo_data import refit_pairs

import synth
from elo_check_runs import SEASON, settings
from elo_check_synth import synth_point

POSTPONED, MOVED_TO = 18, 30
SCHEDULE = synth.schedule


def postponed_schedule() -> list[dict]:
    """The synthetic schedule with GW18's league matches moved to GW30 (kicking off after
    GW30's own), and the EFL Cup tie `cup-10` replaced by `cup-pp`, played in GW18."""
    out = []
    for m in SCHEDULE():
        if m["tournament"] == "prem" and m["gw"] == POSTPONED:
            i = 2 + sum(o["gw"] == MOVED_TO for o in out)  # GW30's own are at +0h and +3h
            m = {**m, "gw": MOVED_TO,
                 "kick": synth.FIRST_KICKOFF + pd.Timedelta(days=7 * MOVED_TO, hours=3 * i)}
        elif m["id"] == "cup-10":
            m = {**m, "id": "cup-pp", "gw": POSTPONED, "played": POSTPONED,
                 "kick": synth.FIRST_KICKOFF + pd.Timedelta(days=7 * POSTPONED)}
        out.append(m)
    return out


def run_settings() -> dict:
    """The synthetic settings, with no leakage cases (not under test here) and GW18, which has
    no rating pairs, out of the ratings' pass mark. `shape_tolerance` is set above every real
    coefficient step, so a run that compared the coefficients with it instead of
    `refit_tolerance` would call every changed pair unchanged (mutant R17)."""
    s = settings(within=False)
    s["perturbation"]["cases"] = []
    s["ratings"]["pass_gameweeks"] = [[16, 17]]
    s["shape_tolerance"] = 0.1
    return s


@pytest.fixture(scope="module")
def postponed(tmp_path_factory: pytest.TempPathFactory, cfg: dict) -> tuple[dict, mock.Mock]:
    """The check on the postponed season, and a spy on its `refit_pairs` call."""
    root = tmp_path_factory.mktemp("postponed")
    with mock.patch.object(synth, "schedule", postponed_schedule):
        for gw in range(1, synth.N_GW + 1):  # no master files: backtest mode never reads them
            synth._write_folder(root / "data" / SEASON, gw)
        synth.write_view_of(root)  # the view every backtest read of 1-37 needs
    spy = mock.Mock(wraps=refit_pairs)
    with synth_point(root / "data"), mock.patch.object(backtest.elo_check, "refit_pairs", spy):
        res = run_check(run_settings(), Models(), synth.synth_cfg(cfg, root), root / "data",
                        point=synth_point)
        res["final_fixtures"] = backtest.elo_check.load_as_of(SEASON, 22, "backtest")[
            "fact_fixture"]  # what the run read at its last target, for the scenario's check
    return res, spy


def pair(refit: pd.DataFrame, as_of: int) -> pd.Series:
    return refit[(refit.from_as_of == as_of) & (refit.to_season == SEASON)].iloc[0]


def test_the_postponed_gameweek_holds_only_the_cup_tie(postponed: tuple[dict, mock.Mock]
                                                         ) -> None:
    """The scenario itself: without a finished cup tie in GW18, mutant R16 would survive."""
    fx = postponed[0]["final_fixtures"]
    week = fx[fx.gw == POSTPONED]
    assert week.match_id.tolist() == ["cup-pp"] and week.finished.all()
    assert (week.tournament != "prem").all()
    moved = fx[fx.match_id.str.startswith(f"m{POSTPONED:02d}-")]
    assert len(moved) == 2 and (moved.gw == MOVED_TO).all()
    league = postponed[1].call_args.args[1][SEASON]
    assert not (league.gw == POSTPONED).any() and (league.gw == POSTPONED - 1).any()
    assert "cup-pp" not in set(league.match_id)


def test_a_wholly_postponed_gameweek_is_an_unchanged_pair_that_passes(
        postponed: tuple[dict, mock.Mock]) -> None:
    """Mutant R16 (the unfiltered `fact_fixture`) dies here: the cup tie would change the pool
    at as-of 18. Mutant R17 (`shape_tolerance`) dies here: every changed pair would fail."""
    res = postponed[0]
    refit = res["refit"]
    still = pair(refit, POSTPONED - 1)
    assert still.to_as_of == POSTPONED
    assert not still.pool_changed and not still.coef_changed and still.ok
    assert still.max_diff <= res["settings"]["refit_tolerance"]
    others = refit.drop(still.name)
    assert len(others) >= 4 and others.pool_changed.all() and others.coef_changed.all()
    assert refit.ok.all() and res["met"]["refit"]


def test_run_check_passes_the_settings_to_the_refit_check(postponed: tuple[dict, mock.Mock]
                                                           ) -> None:
    """Mutant R15 (pool length 1) dies here only: with one synthetic season a pool of one
    season and a pool of two are the same results, so the spy checks the arguments."""
    res, spy = postponed
    s = res["settings"]
    spy.assert_called_once()
    checks, pools, order, length, tol = spy.call_args.args
    assert checks is res["goal_checks"]
    assert order == [SEASON]
    assert length == s["baseline_pool_seasons"] == 2
    assert tol == s["refit_tolerance"] != s["shape_tolerance"]
    assert set(pools) == {SEASON}  # finished league results only (`league_results`)
    assert (pools[SEASON].tournament == "prem").all() and pools[SEASON].finished.all()
