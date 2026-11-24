"""Settings and helpers shared by the Elo check's end-to-end tests on the synthetic upstream.

The honest run itself is the session fixture `honest_run` in conftest.py, so that it is
computed once for every test file that renders it.
"""

from __future__ import annotations

from backtest.elo_check import load_settings

import synth

SEASON = synth.SEASON
INFO = {"date": "2026-11-13", "commit": "abc", "code_clean": "yes", "harness_clean": "yes",
        "model_version": "unset", "upstream_commit": "def", "upstream_time": "t",
        "upstream_clean": "yes",
        "model_yaml_sha256": "1", "settings_sha256": "2", "harness_sha256": "3"}
# The files the harness copies into its scratch upstream copy, from backtest/config.yaml, so a
# file the loader starts reading (shots and incidents, phase 2 task 1) needs no edit here.
FILES = load_settings()["upstream_files"]


def settings(within: bool = True) -> dict:
    """A small window of the synthetic season. As-of 14 has 28 matches, below the 30 minimum."""
    return {
        "mode": "backtest", "seasons": [{"id": SEASON, "target_gameweeks": [15, 22]}],
        "baseline_pool_seasons": 2, "pass_from_gw": 18, "min_bin_count": 5, "concern_min_count": 3,
        "compare_decimals": 9, "calibration_k": 2, "shape_tolerance": 1e-12,
        "refit_tolerance": 1e-9, "concern_spearman_margin": 0.03, "concern_home_share": 0.9,
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


def checklist_row(text: str, item: str) -> str:
    """The report's leakage-checklist row that starts with `item`."""
    return next(ln for ln in text.splitlines() if ln.startswith(f"| {item}"))
