"""The verdict's criteria and the baseline at its call site, on hand-built inputs."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from backtest.elo_check import Models, collect_goals, criteria
from backtest.elo_data import SkipLog

S = {"ratings": {"pass_gameweeks": [[6, 7]]}}


def inputs() -> tuple[pd.DataFrame, dict, dict, dict]:
    """Inputs that meet every criterion."""
    rt = pd.DataFrame({"gw": [5, 6, 7], "mark": ["no pass mark: early", "pass mark", "pass mark"],
                       "passed": [None, True, True]})
    pooled = {"goals_ok": True, "cs_ok": True, "beats_baseline": True}
    leak = {"after": [{"functions": {"elo_ratings": {"changed": 0}, "elo_goals": {"changed": 0},
                                     "planted_leak": {"changed": 5}},
                       "control": {"elo_ratings": {"changed": 3}, "elo_goals": {"changed": 2}}}],
            "within": [{"changed": 0, "control_changed": 4}]}
    stability = {"S1": {"changed": 0, "missing": 0, "extra": 0}}
    return rt, pooled, leak, stability


def test_every_criterion_is_met_on_good_inputs() -> None:
    assert all(criteria(*inputs(), S).values())


def test_a_missing_pass_mark_gameweek_fails_the_ratings() -> None:  # M25
    rt, pooled, leak, stability = inputs()
    assert not criteria(rt[rt.gw != 7], pooled, leak, stability, S)["ratings"]


def test_a_failed_pass_mark_gameweek_fails_the_ratings() -> None:
    rt, pooled, leak, stability = inputs()
    rt.loc[rt.gw == 6, "passed"] = False
    assert not criteria(rt, pooled, leak, stability, S)["ratings"]


def test_a_planted_leak_that_changes_nothing_is_not_caught() -> None:  # M26
    rt, pooled, leak, stability = inputs()
    leak["after"][0]["functions"]["planted_leak"]["changed"] = 0
    assert not criteria(rt, pooled, leak, stability, S)["planted_leak_caught"]


def test_a_within_gameweek_case_with_no_control_change_fails() -> None:  # M27
    rt, pooled, leak, stability = inputs()
    leak["within"][0]["control_changed"] = 0
    assert not criteria(rt, pooled, leak, stability, S)["within_gameweek"]


def test_a_within_gameweek_change_fails() -> None:
    rt, pooled, leak, stability = inputs()
    leak["within"][0]["changed"] = 1
    assert not criteria(rt, pooled, leak, stability, S)["within_gameweek"]


@pytest.mark.parametrize("fn", ["elo_ratings", "elo_goals"])
def test_a_function_the_copy_control_doesnt_move_fails(fn: str) -> None:
    rt, pooled, leak, stability = inputs()
    leak["after"][0]["control"][fn]["changed"] = 0
    assert not criteria(rt, pooled, leak, stability, S)["copy_reached"]


@pytest.mark.parametrize("fn", ["elo_ratings", "elo_goals"])
def test_any_changed_value_fails_the_perturbation(fn: str) -> None:
    rt, pooled, leak, stability = inputs()
    leak["after"][0]["functions"][fn]["changed"] = 1
    assert not criteria(rt, pooled, leak, stability, S)["perturbation"]


@pytest.mark.parametrize("field", ["changed", "missing", "extra"])
def test_any_unstable_read_fails(field: str) -> None:
    rt, pooled, leak, stability = inputs()
    stability["S1"][field] = 1
    assert not criteria(rt, pooled, leak, stability, S)["read_stability"]


# --- the baseline at its call site --------------------------------------------------------

def final_tables() -> dict[str, dict[str, pd.DataFrame]]:
    """One season: GW1 a 3-1, b 1-1 (home mean 2, away 1); GW2 c 0-0, d 4-0."""
    rows = [("a", 1, 1, 2, 3, 1), ("b", 1, 3, 4, 1, 1), ("c", 2, 2, 3, 0, 0), ("d", 2, 4, 1, 4, 0)]
    fx = pd.DataFrame([{"season": "S1", "match_id": m, "gw": g, "kickoff_utc": f"t{g}{m}",
                        "tournament": "prem", "home_team_id": h, "away_team_id": a,
                        "finished": True, "home_goals": hg, "away_goals": ag}
                       for m, g, h, a, hg, ag in rows])
    fx = fx.astype({"home_team_id": "Int64", "away_team_id": "Int64", "home_goals": "Int64",
                    "away_goals": "Int64"})
    teams = pd.DataFrame({"team_id": [1, 2, 3, 4], "name": ["W", "X", "Y", "Z"]})
    return {"S1": {"fact_fixture": fx, "dim_team": teams}}


def fake_goals(season: str, as_of: int, mode: str) -> pd.DataFrame:
    fx = final_tables()[season]["fact_fixture"]
    nxt = fx[fx.gw == as_of + 1]
    rows = []
    for r in nxt.itertuples():
        rows += [(int(r.home_team_id), r.match_id, r.gw, int(r.away_team_id), True, 1.5, 1.0),
                 (int(r.away_team_id), r.match_id, r.gw, int(r.home_team_id), False, 1.0, 1.5)]
    out = pd.DataFrame(rows, columns=["team_id", "match_id", "gw", "opponent_id", "home",
                                      "lambda_for", "lambda_against"])
    return out.assign(p_cs=np.exp(-out.lambda_against))


def test_the_baseline_uses_home_and_away_means_up_to_g_minus_1() -> None:  # M10, M15
    s = {"mode": "backtest", "seasons": [{"id": "S1", "target_gameweeks": [2, 2]}],
         "baseline_pool_seasons": 2}
    df, _ = collect_goals(s, Models(elo_goals=fake_goals), SkipLog({}), final_tables(), "prem")
    base = df.set_index(["match_id", "home"]).base_for
    # Pool = GW1 only: home 2.0, away 1.0. Through GW2 the away mean would be 0.5.
    assert base[("c", True)] == 2.0 and base[("d", True)] == 2.0
    assert base[("c", False)] == 1.0 and base[("d", False)] == 1.0
    row = df[(df.match_id == "d") & df.home].iloc[0]  # 4 goals at rate 2
    assert row.nll_base == pytest.approx(2.0 - 4 * math.log(2.0) + math.log(24))
    assert set(df.team_name) == {"W", "X", "Y", "Z"}
