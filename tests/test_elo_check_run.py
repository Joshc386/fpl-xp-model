"""The whole Elo check, end to end on the synthetic upstream, and the report it writes."""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pandas as pd
import pytest
from backtest.elo_check import Models, run_check
from backtest.elo_data import UnexpectedReadError
from backtest.elo_leakage import peeking_goals
from backtest.elo_report import render

import synth
from elo_check_synth import synth_point
from fpl.models.elo import elo_ratings
from fpl.models.team_goals import elo_goals

SEASON = synth.SEASON
INFO = {"date": "2026-11-13", "commit": "abc", "code_clean": "yes", "harness_clean": "yes",
        "model_version": "unset", "upstream_commit": "def", "upstream_time": "t",
        "upstream_clean": "yes",
        "model_yaml_sha256": "1", "settings_sha256": "2", "harness_sha256": "3"}
FILES = ["fixtures", "matches", "players", "teams", "playerstats", "playermatchstats",
         "player_gameweek_stats"]
HEADINGS = ["Verdict", "Code under test", "Ratings", "Goals calibration",
            "Clean-sheet calibration", "Log-loss against the baseline", "Per season",
            "Early season", "Leakage", "Skipped reads", "Weakest areas", "Concerns",
            "Open questions and blockers"]


def settings(within: bool = True) -> dict:
    """A small window of the synthetic season. As-of 14 has 28 matches, below the 30 minimum."""
    return {
        "mode": "backtest", "seasons": [{"id": SEASON, "target_gameweeks": [15, 22]}],
        "baseline_pool_seasons": 2, "pass_from_gw": 18, "min_bin_count": 5, "concern_min_count": 3,
        "compare_decimals": 9, "calibration_k": 2, "shape_tolerance": 1e-12,
        "concern_spearman_margin": 0.03,
        "goals": {"bin_edges": [0.0, 0.75, 1.25, 1.75], "tolerance": 0.1},
        "clean_sheets": {"bin_width": 0.1, "tolerance": 0.05},
        "ratings": {"season": SEASON, "min_spearman": -1.0, "pass_gameweeks": [[16, 20]],
                    "unscored": [{"range": [1, 15], "why": "early"},
                                 {"range": [21, 38], "why": "late"}]},
        "expected_skips": {"elo_goals": {SEASON: {14: "InsufficientSampleError"}}},
        "perturbation": {"seed": 5, "cases": [{"season": SEASON, "as_of": 20}],
                         "within_gameweek": [{"season": SEASON, "gw": 7}] if within else [],
                         "score_range": [0, 9], "elo_range": [1200.0, 2200.0],
                         "xg_range": [0.0, 4.0]},
        "upstream_files": FILES, "weakest": {"top_n": 3}, "report_dir": "unused",
    }


@pytest.fixture(scope="module")
def honest(synth_upstream: tuple[Path, dict]) -> dict:
    root, cfg = synth_upstream
    with synth_point(root / "data"):
        return run_check(settings(), Models(), cfg, root / "data", point=synth_point)


def test_the_honest_model_passes_every_leakage_check(honest: dict) -> None:
    met = honest["met"]
    assert met["perturbation"] and met["planted_leak_caught"] and met["copy_reached"]
    assert met["within_gameweek"] and met["read_stability"]
    control = honest["leakage"]["after"][0]["control"]
    assert control["elo_goals"]["changed"] > 0 and control["elo_ratings"]["changed"] > 0
    assert honest["non_league_rows"] == 0  # the cup ties never reach the ratings


def test_targets_are_scored_once_per_team_fixture_and_skips_are_counted(honest: dict) -> None:
    sched = [m for m in synth.schedule() if m["tournament"] == "prem" and 16 <= m["gw"] <= 22]
    assert len(honest["goals"]) == 2 * len(sched)  # target 15 needs as-of 14, which raises
    assert [(s.function, s.as_of, s.error) for s in honest["skips"].skips] == [
        ("elo_goals", 14, "InsufficientSampleError")]
    assert not honest["goals"].duplicated(["match_id", "home"]).any()


def test_the_goal_checks_cover_every_as_of_with_both_reads(honest: dict) -> None:
    """One row per as-of with both a goals and a ratings read, holding the form-free shape
    check and the log-linear fit (information only). Neither is asserted on the synthetic
    model, whose behaviour isn't the harness's to test; the maths is tested on hand-built input
    in test_elo_check_data. The contract's identities hold for any version of the model."""
    checks = honest["goal_checks"]
    assert len(checks) == 7
    for col in ("not_rising", "tie_mismatch", "max_resid", "intercept"):
        assert checks[col].notna().all()
    assert checks.home_above.between(0, 1).sum() > 0  # NaN where no home gap is in range
    assert checks.p_cs_err.max() < 1e-12 and checks.mirror_err.max() < 1e-12


def test_the_report_has_every_section_in_order(honest: dict) -> None:
    text = render(honest, INFO)
    found = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
    assert found == HEADINGS
    assert "InsufficientSampleError" in text and "Leak caught" in text
    assert "GW16-20" in text and "True" not in text  # labels from the settings; no raw bools
    assert "Limit applied" in text and "Copy reached" in text and "Harness code" in text
    assert "Pooled from GW18." in text  # from pass_from_gw, not a fixed GW6


def checklist_row(text: str, item: str) -> str:
    return next(ln for ln in text.splitlines() if ln.startswith(f"| {item}"))


def test_the_checklist_evidence_follows_the_results(honest: dict) -> None:
    good = checklist_row(render(honest, INFO), "Features for g use nothing")
    assert "| pass |" in good and "0 output values changed" in good
    assert "caught in 1 of 1" in good
    bad = copy.deepcopy(honest)
    bad["leakage"]["after"][0]["functions"]["elo_goals"]["changed"] = 3
    bad["met"]["perturbation"] = False
    row = checklist_row(render(bad, INFO), "Features for g use nothing")
    assert "| FAIL |" in row and "3 output values changed" in row
    window = checklist_row(render(bad, INFO), "Rolling windows")
    assert "| FAIL |" in window and "3 output values changed" in window


def test_the_deadline_row_needs_the_copy_control(honest: dict) -> None:  # N13
    bad = copy.deepcopy(honest)
    bad["leakage"]["after"][0]["control"]["elo_goals"]["changed"] = 0
    bad["met"]["copy_reached"] = False
    row = checklist_row(render(bad, INFO), "Features for g use nothing")
    assert "| FAIL |" in row and "reached both functions in 0 of 1" in row


def test_the_refit_row_doesnt_depend_on_the_models_form(honest: dict) -> None:
    other_form = copy.deepcopy(honest)
    other_form["goal_checks"]["max_resid"] = 0.5  # far from log-linear
    row = checklist_row(render(other_form, INFO), "Team ratings refitted")
    assert "| pass |" in row and "residual" not in row
    unstable = copy.deepcopy(honest)
    unstable["stability"][SEASON]["extra"] = 2
    unstable["met"]["read_stability"] = False
    row = checklist_row(render(unstable, INFO), "Team ratings refitted")
    assert "| FAIL |" in row and "2 rows from after the as-of" in row
    frozen = copy.deepcopy(honest)
    frozen["goal_checks"][["intercept", "gap", "home"]] = 0.1  # coefficients never change
    assert "| FAIL |" in checklist_row(render(frozen, INFO), "Team ratings refitted")


def test_a_shape_violation_is_a_concern_but_another_form_is_not(honest: dict) -> None:
    ok = copy.deepcopy(honest)
    ok["goal_checks"][["not_rising", "tie_mismatch"]] = 0
    ok["goal_checks"]["max_resid"] = 0.5
    assert "rating gap and home" not in render(ok, INFO).split("## Concerns")[1]
    bad = copy.deepcopy(ok)
    bad["goal_checks"].loc[bad["goal_checks"].index[0], "not_rising"] = 2
    assert "rating gap and home" in render(bad, INFO).split("## Concerns")[1]


def test_a_leaky_goals_model_fails_the_check(synth_upstream: tuple[Path, dict]) -> None:
    root, cfg = synth_upstream
    s = settings(within=False) | {"seasons": [{"id": SEASON, "target_gameweeks": [20, 21]}]}
    with synth_point(root / "data"):
        res = run_check(s, Models(elo_ratings=elo_ratings, elo_goals=peeking_goals), cfg,
                        root / "data", point=synth_point)
    assert not res["met"]["perturbation"] and not res["passed"]
    assert "perturbation" in res["missed"]


def test_an_unexpected_exception_stops_the_run(synth_upstream: tuple[Path, dict]) -> None:
    def broken(season: str, as_of: int, mode: str) -> pd.DataFrame:
        if as_of == 19:
            raise KeyError("lambda_for")
        return elo_goals(season, as_of, mode)

    root, cfg = synth_upstream
    s = settings(within=False) | {"seasons": [{"id": SEASON, "target_gameweeks": [19, 20]}]}
    with synth_point(root / "data"), pytest.raises(UnexpectedReadError, match="as-of 19"):
        run_check(s, Models(elo_goals=broken), cfg, root / "data", point=synth_point)
