"""The whole Elo check, end to end on the synthetic upstream, and the report it writes."""

from __future__ import annotations

import copy
import inspect
import re
from pathlib import Path

import backtest.perturb
import pandas as pd
import pytest
from backtest.elo_check import Models, run_check, run_leakage
from backtest.elo_data import UnexpectedReadError
from backtest.elo_leakage import peeking_goals
from backtest.elo_report import render

import synth
from elo_check_synth import real_redirect_to_synth, synth_point
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


@pytest.fixture(scope="module")
def honest_run(synth_upstream: tuple[Path, dict]) -> tuple[dict, list[Path]]:
    """The check with no `point`, so through the production `perturb.redirect`, and the data
    copies that redirect was pointed at."""
    root, cfg = synth_upstream
    seen: list[Path] = []
    with synth_point(root / "data"), real_redirect_to_synth(seen):
        return run_check(settings(), Models(), cfg, root / "data"), seen


@pytest.fixture(scope="module")
def honest(honest_run: tuple[dict, list[Path]]) -> dict:
    return honest_run[0]


def test_by_default_the_check_reads_the_copy_through_perturb_redirect(
        honest_run: tuple[dict, list[Path]], synth_upstream: tuple[Path, dict]) -> None:
    """Mutant P10 (`run_check`'s default `point` a no-op) dies here: the redirect would never be
    entered, and the copy control and the planted leak would read the clean source."""
    res, seen = honest_run
    src = synth_upstream[0] / "data"
    # Per after-as-of case: clean, corrupted and control runs; per within case: clean and dirty.
    assert len(seen) == 3 * len(res["leakage"]["after"]) + 2 * len(res["leakage"]["within"])
    assert len(set(seen)) == 1 and seen[0] != src and seen[0].name == "data"
    assert res["met"]["copy_reached"] and res["met"]["planted_leak_caught"]


def test_run_checks_default_point_is_the_production_redirect() -> None:
    """Mutant P10 dies here without relying on the test double above being right."""
    point = inspect.signature(run_check).parameters["point"]
    assert point.default is backtest.perturb.redirect


def test_run_leakage_has_no_default_point() -> None:
    """`run_check` always passes `point`; a default here would be dead code."""
    point = inspect.signature(run_leakage).parameters["point"]
    assert point.default is inspect.Parameter.empty


def test_the_honest_model_passes_every_leakage_check(honest: dict) -> None:
    met = honest["met"]
    assert met["perturbation"] and met["planted_leak_caught"] and met["copy_reached"]
    assert met["within_gameweek"] and met["read_stability"] and met["refit"]
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


def test_the_honest_run_has_a_refit_pair_per_consecutive_goals_read(honest: dict) -> None:
    refit, checks = honest["refit"], honest["goal_checks"]
    assert len(refit) == len(checks) - 1 >= 3
    assert list(zip(refit.to_season, refit.to_as_of, strict=True)) == list(
        zip(checks.season.iloc[1:], checks.as_of.iloc[1:], strict=True))
    assert refit.pool_changed.all() and refit.coef_changed.all()  # results every gameweek
    assert refit.max_diff.min() > 1e3 * honest["settings"]["refit_tolerance"]


def failing_refit(honest: dict, i: int, **change: object) -> dict:
    """The honest run with refit pair `i` changed and the verdict recomputed."""
    bad = copy.deepcopy(honest)
    r = bad["refit"]
    for k, v in change.items():
        r.loc[r.index[i], k] = v
    r["ok"] = r.pool_changed == r.coef_changed
    bad["met"]["refit"] = False
    bad["passed"], bad["missed"] = False, ["refit"]
    return bad


def test_the_refit_row_doesnt_depend_on_the_models_form(honest: dict) -> None:
    other_form = copy.deepcopy(honest)
    other_form["goal_checks"]["max_resid"] = 0.5  # far from log-linear
    row = checklist_row(render(other_form, INFO), "Team ratings refitted")
    assert "| pass |" in row and "residual" not in row


def test_the_refit_row_shows_read_stability_and_refit(honest: dict) -> None:
    row = checklist_row(render(honest, INFO), "Team ratings refitted")
    n = len(honest["refit"])
    assert "| pass |" in row and f"{n} consecutive pairs" in row and "Failing pairs: none" in row
    unstable = copy.deepcopy(honest)
    unstable["stability"][SEASON]["extra"] = 2
    unstable["met"]["read_stability"] = False
    row = checklist_row(render(unstable, INFO), "Team ratings refitted")
    assert "| FAIL |" in row and "2 rows from after the as-of" in row
    assert "| FAIL |" in checklist_row(render(failing_refit(honest, 1, coef_changed=False), INFO),
                                       "Team ratings refitted")


def test_the_refit_evidence_names_each_failing_pair(honest: dict) -> None:
    r = honest["refit"].iloc[1]
    bad = failing_refit(honest, 1, coef_changed=False, max_diff=0.0)
    text = render(bad, INFO)
    row = checklist_row(text, "Team ratings refitted")
    assert "| FAIL |" in row
    assert (f"{r.from_season} as-of {r.from_as_of} to {r.to_season} as-of {r.to_as_of} "
            "(pool changed, coefficients unchanged" in row)
    assert "**FAIL.** Criteria missed: refit." in text
    r2 = honest["refit"].iloc[2]
    row = checklist_row(render(failing_refit(honest, 2, pool_changed=False), INFO),
                        "Team ratings refitted")
    assert (f"{r2.from_season} as-of {r2.from_as_of} to {r2.to_season} as-of {r2.to_as_of} "
            "(pool unchanged, coefficients changed" in row)


def test_the_verdict_lists_the_refit_criterion(honest: dict) -> None:
    verdict = render(honest, INFO).split("## Code under test")[0]
    assert "change between consecutive goals reads when the fitting pool changed" in verdict
    assert "1e-09" in verdict


def test_the_report_text_describes_the_refit_rule(honest: dict) -> None:
    text = render(honest, INFO)
    assert "needs a look by hand" not in text and "legitimately" not in text
    assert "wholly postponed" in text and "must not change" in text


@pytest.mark.parametrize(("last", "rows"), [(20, 0), (21, 1)])
def test_a_run_with_fewer_than_two_goal_checks_fails_the_refit_criterion(
        synth_upstream: tuple[Path, dict], last: int, rows: int) -> None:
    """Targets from GW20: the goals read at as-of 19 has no ratings read to pair with."""
    root, cfg = synth_upstream
    s = settings(within=False) | {"seasons": [{"id": SEASON, "target_gameweeks": [20, last]}]}
    with synth_point(root / "data"):
        res = run_check(s, Models(), cfg, root / "data", point=synth_point)
    assert len(res["goal_checks"]) == rows and len(res["refit"]) == 0
    assert not res["met"]["refit"] and "refit" in res["missed"]
    if rows:  # with no goal checks at all the shape section has no columns to report
        row = checklist_row(render(res, INFO), "Team ratings refitted")
        assert "| FAIL |" in row and "0 consecutive pairs" in row


def test_a_shape_violation_is_a_concern_but_another_form_is_not(honest: dict) -> None:
    ok = copy.deepcopy(honest)
    ok["goal_checks"][["not_rising", "tie_mismatch"]] = 0
    ok["goal_checks"]["max_resid"] = 0.5
    assert "rating gap and home" not in render(ok, INFO).split("## Concerns")[1]
    bad = copy.deepcopy(ok)
    bad["goal_checks"].loc[bad["goal_checks"].index[0], "not_rising"] = 2
    assert "rating gap and home" in render(bad, INFO).split("## Concerns")[1]


def concerns(res: dict) -> str:
    return render(res, INFO).split("## Concerns")[1]


def with_home_share(honest: dict, shares: list[float]) -> dict:
    """The honest run with no shape violation and `shares` repeated over the as-of reads."""
    out = copy.deepcopy(honest)
    c = out["goal_checks"]
    c[["not_rising", "tie_mismatch"]] = 0
    c["home_above"] = (shares * len(c))[:len(c)]
    return out


def test_the_shape_text_claims_no_more_than_it_checks(honest: dict) -> None:
    """The two shape checks are necessary conditions only; the home share fails nothing."""
    low = with_home_share(honest, [0.0])
    text = render(low, INFO)
    assert "breaks one of these" not in text and "necessary, not sufficient" in text
    assert "lowest share (Concern below 0.9) | 0.000 |" in text
    assert "raises no concern" not in text and "(information) |" not in text


def test_a_low_home_share_is_a_concern(honest: dict) -> None:
    assert "home rows" not in concerns(with_home_share(honest, [1.0]))
    low = with_home_share(honest, [1.0])
    c = low["goal_checks"]
    c.loc[c.index[2], "home_above"] = 0.5
    x, a = c.season.iloc[2], c.as_of.iloc[2]
    text = concerns(low)
    assert "home rows" in text and f"0.500 at {x} as-of {a}" in text and "below 0.9" in text
    assert f"1 of {len(c)} reads" in text


def test_a_home_share_of_exactly_the_threshold_is_not_a_concern(honest: dict) -> None:
    assert "home rows" not in concerns(with_home_share(honest, [0.9]))
    assert "home rows" in concerns(with_home_share(honest, [0.9 - 1e-9]))


def test_reads_with_no_home_share_are_ignored(honest: dict) -> None:
    nan = float("nan")
    assert "home rows" not in concerns(with_home_share(honest, [nan]))  # every read NaN
    assert "home rows" not in concerns(with_home_share(honest, [nan, 1.0]))
    mixed = concerns(with_home_share(honest, [nan, 0.5]))
    assert "home rows" in mixed and "0.500" in mixed


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
