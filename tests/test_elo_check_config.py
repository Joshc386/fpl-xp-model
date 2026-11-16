"""backtest/config.yaml pinned against brief section 7 and the contract's Elo seed notes.

A change to any value here is a change to the gate, which is Josh's decision: update the brief
first, then this test.
"""

from __future__ import annotations

import copy
from pathlib import Path

import backtest.elo_check
import pytest
import yaml
from backtest.elo_check import (
    Models,
    check_pool_settings,
    expected_skips,
    load_settings,
    run_check,
)
from backtest.elo_data import HarnessError

from fpl.ingest import ROOT, load_config
from fpl.models.elo import MissingSeedError
from fpl.models.team_goals import InsufficientSampleError

S = load_settings()


def gameweeks(ranges: list[list[int]]) -> set[int]:
    return {g for lo, hi in ranges for g in range(lo, hi + 1)}


def test_mode_seasons_and_window() -> None:
    assert S["mode"] == "backtest"
    assert S["seasons"] == [{"id": "2025-2026", "target_gameweeks": [1, 38]},
                            {"id": "2026-2027", "target_gameweeks": [1, 10]}]
    assert S["baseline_pool_seasons"] == 2  # this season and last
    assert S["pass_from_gw"] == 6


def test_calibration_marks() -> None:  # M37
    assert S["goals"] == {"bin_edges": [0.0, 0.75, 1.25, 1.75], "tolerance": 0.1}
    assert S["clean_sheets"] == {"bin_width": 0.1, "tolerance": 0.05}
    assert S["min_bin_count"] == 100
    assert S["calibration_k"] == 2


def test_ratings_marks() -> None:  # M39
    r = S["ratings"]
    assert r["season"] == "2025-2026" and r["min_spearman"] == 0.9
    assert gameweeks(r["pass_gameweeks"]) == set(range(6, 27)) | {33}
    unscored = gameweeks([u["range"] for u in r["unscored"]])
    assert unscored == set(range(1, 6)) | set(range(27, 33)) | set(range(34, 39))
    assert not unscored & gameweeks(r["pass_gameweeks"])


def test_expected_skips_are_exactly_the_contracts() -> None:  # M38
    want = {
        "elo_ratings": {"2025-2026": {0: MissingSeedError},
                        "2026-2027": {0: MissingSeedError, 1: MissingSeedError}},
        "elo_goals": {"2025-2026": {0: MissingSeedError, 1: InsufficientSampleError,
                                    2: InsufficientSampleError},
                      "2026-2027": {0: MissingSeedError, 1: MissingSeedError}},
    }
    assert expected_skips(S) == want


def test_refit_tolerance_and_report_thresholds() -> None:
    # Coefficient noise at an unchanged fit is about 1e-14; a real refit moves them by 1e-3.
    assert S["refit_tolerance"] == 1e-9
    assert S["concern_home_share"] == 0.9  # a Concern only, never the verdict
    assert S["shape_tolerance"] == 1e-12 and S["concern_spearman_margin"] == 0.03


def test_perturbation_cases_are_the_briefs() -> None:
    p = S["perturbation"]
    assert [(c["season"], c["as_of"]) for c in p["cases"]] == [
        ("2025-2026", 5), ("2025-2026", 20), ("2025-2026", 33), ("2026-2027", 3),
        ("2026-2027", 9)]
    assert {"season": "2025-2026", "gw": 33} in p["within_gameweek"]  # the double gameweek


def test_an_unknown_exception_name_is_rejected() -> None:
    with pytest.raises(KeyError):
        expected_skips({"expected_skips": {"elo_goals": {"2025-2026": {0: "ValueError"}}}})


# --- the pool settings against the model's (brief section 7: the baseline pool is the pool
# the Elo goals model fits on) ------------------------------------------------------------

MODEL = yaml.safe_load((ROOT / "config" / "model.yaml").read_text(encoding="utf-8"))
PIPELINE = load_config(ROOT / "config" / "pipeline.yaml")


def test_the_pool_settings_agree_with_the_models() -> None:
    check_pool_settings(S, MODEL, PIPELINE)
    assert S["seasons"][0]["id"] == MODEL["elo"]["start_season"]
    assert S["baseline_pool_seasons"] == MODEL["goals_model"]["pool_seasons"]


def season(x: str) -> dict:
    return {"id": x, "target_gameweeks": [1, 38]}


def pipeline(*ids: str) -> dict:
    return {"seasons": [{"id": x, "gameweeks": 38} for x in ids]}


TWO = ("2025-2026", "2026-2027")


@pytest.mark.parametrize(("seasons", "listed", "start", "pool", "match"), [
    (TWO, TWO, "2024-2025", 2, "start_season"),                         # start not in pipeline
    (["2026-2027"], TWO, "2025-2026", 2, "start_season"),               # the run starts later
    (["2026-2027", "2025-2026"], TWO, "2025-2026", 2, "start_season"),  # out of order
    (["2025-2026", "2027-2028"], TWO, "2025-2026", 2, "start_season"),  # not the next season
    (TWO, ("2025-2026", "2027-2028"), "2025-2026", 2, "start_season"),  # the pipeline's order
    (TWO, TWO, "2025-2026", 3, "pool_seasons"),
    (TWO, TWO, "2025-2026", 1, "pool_seasons"),
])
def test_pool_settings_that_disagree_with_the_model_raise(
        seasons: list[str], listed: tuple[str, ...], start: str, pool: int, match: str) -> None:
    model = copy.deepcopy(MODEL)
    model["elo"]["start_season"] = start
    model["goals_model"]["pool_seasons"] = pool
    s = copy.deepcopy(S) | {"seasons": [season(x) for x in seasons]}
    with pytest.raises(HarnessError, match=match):
        check_pool_settings(s, model, pipeline(*listed))


@pytest.mark.parametrize(("seasons", "listed"), [
    (["2025-2026", "2027-2028"], ("2025-2026", "2027-2028")),         # the pipeline skips one
    (TWO, ("2024-2025", *TWO)),                                       # the pipeline starts earlier
    (["2025-2026"], TWO),                                             # the run's first seasons
])
def test_the_season_order_is_the_pipelines_from_the_start_season_on(
        seasons: list[str], listed: tuple[str, ...]) -> None:
    """The order comes from config/pipeline.yaml, as the Elo run's own does, not from the ids."""
    s = copy.deepcopy(S) | {"seasons": [season(x) for x in seasons]}
    check_pool_settings(s, MODEL, pipeline(*listed))


@pytest.mark.parametrize("change", [{"baseline_pool_seasons": 3},
                                    {"seasons": [season("2026-2027")]}])
def test_run_check_checks_the_pool_settings_before_reading_anything(
        monkeypatch: pytest.MonkeyPatch, change: dict) -> None:
    """Against the real config/model.yaml. If the check were missing, the run would go on to
    read data: `final_tables` is made to raise first, so this test never reads (the real
    settings include 2026/27, the holdout)."""
    def no_reads(s: dict) -> dict:
        raise AssertionError("run_check read data before checking its pool settings")

    monkeypatch.setattr(backtest.elo_check, "final_tables", no_reads)
    s = copy.deepcopy(S) | change
    with pytest.raises(HarnessError, match="model.yaml"):
        run_check(s, Models(), PIPELINE, Path("unused"))
