"""The whole Elo check, end to end on the synthetic upstream, and the report it writes."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest
import yaml
from backtest.elo_check import Models, run_check, run_info
from backtest.elo_data import UnexpectedReadError
from backtest.elo_leakage import peeking_goals
from backtest.elo_report import render
from backtest.perturb import redirect

import synth
from fpl.ingest import ROOT, load_config
from fpl.models.elo import elo_ratings
from fpl.models.team_goals import elo_goals

SEASON = synth.SEASON
PCFG_ROOT = ROOT
PCFG = load_config(ROOT / "config" / "pipeline.yaml")
CHECKOUT = ROOT / PCFG["upstream"]["checkout_path"]
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
        "compare_decimals": 9, "goals": {"bin_edges": [0.0, 0.75, 1.25, 1.75], "tolerance": 0.1},
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
    with redirect(cfg):
        return run_check(settings(), Models(), cfg, root / "data")


def test_the_honest_model_passes_every_leakage_check(honest: dict) -> None:
    met = honest["met"]
    assert met["perturbation"] and met["planted_leak_caught"]
    assert met["within_gameweek"] and met["read_stability"]
    assert honest["non_league_rows"] == 0  # the cup ties never reach the ratings


def test_targets_are_scored_once_per_team_fixture_and_skips_are_counted(honest: dict) -> None:
    sched = [m for m in synth.schedule() if m["tournament"] == "prem" and 16 <= m["gw"] <= 22]
    assert len(honest["goals"]) == 2 * len(sched)  # target 15 needs as-of 14, which raises
    assert [(s.function, s.as_of, s.error) for s in honest["skips"].skips] == [
        ("elo_goals", 14, "InsufficientSampleError")]
    assert not honest["goals"].duplicated(["match_id", "home"]).any()


def test_the_goals_output_is_the_claimed_log_linear_poisson(honest: dict) -> None:
    claims = honest["claims"]
    assert len(claims) == 7 and claims.max_resid.max() < 1e-6
    assert claims.p_cs_err.max() < 1e-12 and claims.mirror_err.max() < 1e-12


def test_the_report_has_every_section_in_order(honest: dict) -> None:
    info = {"date": "2026-11-13", "commit": "abc", "code_clean": "yes",
            "model_version": "unset", "upstream_commit": "def", "upstream_time": "t",
            "model_yaml_sha256": "1", "settings_sha256": "2"}
    text = render(honest, info)
    found = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
    assert found == HEADINGS
    assert "InsufficientSampleError" in text and "Leak caught" in text
    assert "GW16-20" in text and "True" not in text  # labels from the settings; no raw bools


def test_a_leaky_goals_model_fails_the_check(synth_upstream: tuple[Path, dict]) -> None:
    root, cfg = synth_upstream
    s = settings(within=False) | {"seasons": [{"id": SEASON, "target_gameweeks": [20, 21]}]}
    with redirect(cfg):
        res = run_check(s, Models(elo_ratings=elo_ratings, elo_goals=peeking_goals), cfg,
                        root / "data")
    assert not res["met"]["perturbation"] and not res["passed"]
    assert "perturbation" in res["missed"]


def test_an_unexpected_exception_stops_the_run(synth_upstream: tuple[Path, dict]) -> None:
    def broken(season: str, as_of: int, mode: str) -> pd.DataFrame:
        if as_of == 19:
            raise KeyError("lambda_for")
        return elo_goals(season, as_of, mode)

    root, cfg = synth_upstream
    s = settings(within=False) | {"seasons": [{"id": SEASON, "target_gameweeks": [19, 20]}]}
    with redirect(cfg), pytest.raises(UnexpectedReadError, match="as-of 19"):
        run_check(s, Models(elo_goals=broken), cfg, root / "data")


@pytest.mark.skipif(not (PCFG_ROOT / ".git").exists() or not CHECKOUT.exists(),
                    reason="no git checkout of the repo or of upstream")
def test_run_info_records_the_commits_and_hashes() -> None:
    info = run_info(PCFG)
    assert re.fullmatch(r"[0-9a-f]{40}", info["commit"])
    assert re.fullmatch(r"[0-9a-f]{64}", info["model_yaml_sha256"])
    model = yaml.safe_load((ROOT / "config" / "model.yaml").read_text(encoding="utf-8"))
    assert info["model_version"] == str(model.get("model_version") or "unset")
