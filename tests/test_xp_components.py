"""Component diagnostics against the hand-off interfaces, on hand-built frames: outcomes for
p_60, clean sheets, player goals and team goals, the Europe split and "not built"."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from backtest.elo_data import HarnessError
from backtest.xp_components import (
    minutes_summary,
    player_rows,
    resolve,
    team_rows,
)

# GW5: club 1 plays once (m5, at home to 2, lost 0-2); club 3 plays twice (a 1-0 home win in
# d1 and a 0-0 draw away in d2).
FINAL = {
    "fact_fixture": pd.DataFrame({
        "match_id": ["m5", "d1", "d2"], "gw": 5, "tournament": "prem",
        "home_team_id": [1, 3, 4], "away_team_id": [2, 5, 3], "finished": True,
        "stats_complete": [True, True, False], "home_goals": [0, 1, 0],
        "away_goals": [2, 0, 0]}),
    "fact_player_match": pd.DataFrame({"player_id": [30, 30, 31], "match_id": ["d1", "d1", "d1"],
                                       "minutes": [90, 90, 20], "goals": [1, 1, 0]}).iloc[[0, 2]],
}
SCORED = pd.DataFrame({"player_id": [10, 11, 30, 31], "team_id": [1, 1, 3, 3],
                       "fixtures": [1, 1, 2, 2], "minutes": [90, 30, 150, 20],
                       "goals_conceded": [0, 0, 0, 1], "p60_base": [1.0, 0.0, 0.5, 0.0]})


def out(rows: list[tuple[int, str, float]], col: str) -> pd.DataFrame:
    return pd.DataFrame([{"player_id": p, "match_id": m, "gw": 5, col: v} for p, m, v in rows]
                        + [{"player_id": 10, "match_id": "m6", "gw": 6, col: 0.9}])


def test_p60_outcomes_use_fpl_minutes_in_a_single_and_match_minutes_in_a_double() -> None:
    o = out([(10, "m5", 0.9), (11, "m5", 0.2), (30, "d1", 0.8), (30, "d2", 0.7),
             (31, "d1", 0.1), (99, "m5", 0.5)], "p_60")
    rows = player_rows(o, 5, SCORED, FINAL, "p_60", "p60", europe={3}, long_minutes=60)
    got = rows.set_index(["player_id", "match_id"])
    # 10 played 90 (FPL); 11 played 30; 30 played 90 in d1 and has no d2 row; 31 played 20.
    assert got.outcome.to_dict() == {(10, "m5"): 1, (11, "m5"): 0, (30, "d1"): 1,
                                     (30, "d2"): 0, (31, "d1"): 0}
    assert got.europe.to_dict()[(30, "d1")] and not got.europe.to_dict()[(10, "m5")]
    assert 99 not in rows.player_id.values  # not in the evaluation set: not scored


def test_clean_sheet_and_goal_outcomes() -> None:
    cs = player_rows(out([(10, "m5", 0.3), (30, "d1", 0.4), (30, "d2", 0.5)], "p_cs"), 5,
                     SCORED, FINAL, "p_cs", "cs", europe=set(), long_minutes=60)
    assert cs.set_index("match_id").outcome.to_dict() == {"m5": 1, "d1": 1, "d2": 0}
    # FPL says 10 conceded 0 while on the pitch in m5 (the club conceded 2 after he went off).
    goals = player_rows(out([(30, "d1", 0.4), (31, "d1", 0.1), (30, "d2", 0.2)], "xg"), 5,
                        SCORED, FINAL, "xg", "goals", europe=set(), long_minutes=60)
    # d2 isn't complete, so its player goals aren't known: dropped.
    assert goals.set_index("player_id").outcome.to_dict() == {30: 1, 31: 0}


def test_team_goal_outcomes_are_the_clubs_goals_in_the_fixture() -> None:
    o = pd.DataFrame({"team_id": [1, 2, 3, 3], "match_id": ["m5", "m5", "d1", "d2"], "gw": 5,
                      "lambda_for": [1.0, 1.5, 2.0, 0.5]})
    got = team_rows(o, 5, FINAL, "lambda_for", europe={3}).set_index(["team_id", "match_id"])
    assert got.outcome.to_dict() == {(1, "m5"): 0, (2, "m5"): 2, (3, "d1"): 1, (3, "d2"): 0}


def test_minutes_summary_gives_brier_for_the_model_and_baseline_split_by_europe() -> None:
    rows = pd.DataFrame({"pred": [1.0, 0.0, 0.5, 0.5], "outcome": [1, 0, 1, 0],
                         "p60_base": [0.0, 0.0, 1.0, 1.0], "europe": [False, False, True, True]})
    got = minutes_summary(rows).set_index("group")
    assert got.loc["all", "n"] == 4
    assert got.loc["all", "brier"] == pytest.approx(0.125)
    assert got.loc["all", "brier_baseline"] == pytest.approx(0.5)
    assert got.loc["Europe", "brier"] == pytest.approx(0.25)
    assert got.loc["rest", "brier"] == pytest.approx(0.0)
    assert got.loc["rest", "observed"] == pytest.approx(0.5)


def test_resolve_reads_only_a_missing_module_as_not_built() -> None:
    assert resolve("fpl.models.no_such_component:fn") is None
    assert resolve(None) is None  # deliberately unmapped: not named in the contract yet
    assert resolve("backtest.xp_metrics:brier").__name__ == "brier"
    with pytest.raises(HarnessError, match="has no attribute 'no_such_function'"):
        resolve("fpl.models.team_goals:no_such_function")
    with pytest.raises(HarnessError, match="module:function"):
        resolve("no_colon")


def test_resolve_compares_missing_module_names_on_dot_boundaries(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = tmp_path / "xpprobe"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    # `attack` exists but imports a missing `att`: a broken component, not an unbuilt one.
    (pkg / "attack.py").write_text("import xpprobe.att\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(ModuleNotFoundError, match="xpprobe.att"):
        resolve("xpprobe.attack:attack")
    assert resolve("xpprobe.defence:defence") is None
    assert resolve("no_such_package.minutes:player_minutes") is None


def test_a_component_missing_its_keys_stops_the_run() -> None:
    with pytest.raises(HarnessError, match="match_id"):
        player_rows(out([(10, "m5", 0.9)], "p_60").drop(columns="match_id"), 5, SCORED,
                    FINAL, "p_60", "p60", europe=set(), long_minutes=60)
