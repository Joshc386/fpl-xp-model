"""How the xP backtest resolves its settings: the model and components by import path, and the
reads that raise by design."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from backtest.elo_check import load_settings
from backtest.elo_data import HarnessError
from backtest.xp_inputs import long_min_minutes
from backtest.xp_metrics import brier
from backtest.xp_settings import (
    Predictors,
    config_hashes,
    expected_skips,
    load_predictors,
)

from fpl.models.team_goals import InsufficientSampleError

S = load_settings()["xp_backtest"]


def test_a_baselines_only_run_loads_no_model_or_component() -> None:
    assert load_predictors(S, baselines_only=True) == Predictors()


def test_only_built_components_are_loaded_and_a_wrong_name_stops_the_run() -> None:
    s = copy.deepcopy(S)
    s["model"]["callable"] = "backtest.xp_metrics:brier"
    s["components"] = {"minutes": {**s["components"]["minutes"],
                                   "callable": "fpl.models.not_built_yet:player_minutes"},
                       "team_goals": {**s["components"]["team_goals"], "callable": None}}
    got = load_predictors(s, baselines_only=False)
    assert got.model is brier and got.components == {}
    s["components"]["minutes"]["callable"] = "backtest.xp_metrics:no_such_function"
    with pytest.raises(HarnessError, match="no_such_function"):
        load_predictors(s, baselines_only=False)


def test_the_components_are_mapped_to_their_contract_names() -> None:
    comps = S["components"]
    assert comps["minutes"]["callable"] == "fpl.models.minutes:player_minutes"
    assert comps["team_goals"]["callable"] is None  # phase 2's function isn't named yet
    for name, c in comps.items():
        assert {"callable", "column", "kind", "outcome", "edges"} <= set(c), name
    assert S["model"]["callable"] == "fpl.xp:xp"


def test_a_component_without_its_outcome_or_bins_stops_the_run() -> None:
    s = copy.deepcopy(S)
    s["components"]["saves"] = {"callable": "backtest.xp_metrics:brier", "column": "x"}
    with pytest.raises(HarnessError, match="saves"):
        load_predictors(s, baselines_only=False)


def test_expected_skips_resolve_to_exception_classes() -> None:
    s = {"expected_skips": {"model": {"2025-2026": {
        1: "fpl.models.team_goals:InsufficientSampleError"}}}}
    assert expected_skips(s) == {"model": {"2025-2026": {1: InsufficientSampleError}}}
    assert expected_skips({"expected_skips": {}}) == {}
    with pytest.raises(HarnessError, match="not an exception class"):
        expected_skips({"expected_skips": {"model": {"2025-2026": {
            1: "backtest.xp_metrics:brier"}}}})


def test_the_gate_and_calibration_bins_are_brief_section_7s() -> None:
    """Josh's thresholds: changed only on his decision, never to make a run pass."""
    assert S["metrics"]["calibration_edges"] == [0, 1, 2, 3, 4, 5, 6, 7, 8]
    assert {k: S["gate"][k] for k in ("beat_share", "calibration_tolerance",
                                      "calibration_min_count")} == {
        "beat_share": 0.6, "calibration_tolerance": 0.3, "calibration_min_count": 200}
    assert S["evaluation_set"]["previous_matches"] == 3


def test_the_60_minute_line_comes_from_the_scoring_rules() -> None:
    assert long_min_minutes() == 60
    with pytest.raises(FileNotFoundError):
        long_min_minutes(Path(__file__).parent / "no_such.yaml")


def test_the_run_records_the_hashes_of_every_config_it_reads(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    for name in ("pipeline.yaml", "scoring.yaml"):
        (tmp_path / "config" / name).write_text(name, encoding="utf-8")
    got = config_hashes(tmp_path)
    assert set(got) == {"pipeline_yaml_sha256", "scoring_yaml_sha256"}
    assert got["pipeline_yaml_sha256"] != got["scoring_yaml_sha256"]
    assert len(got["scoring_yaml_sha256"]) == 64
