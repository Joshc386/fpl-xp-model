"""The outside-source Elo check's report: every section the method requires, the credit line,
and a report name that never overwrites an earlier one."""

from __future__ import annotations

from pathlib import Path

import pytest
from backtest.beyondelo_check import run, run_check
from backtest.beyondelo_report import render

from beyondelo_check_synth import S1, S2, settings, world

Report = tuple[str, dict]
INFO = {"date": "2026-11-17", "commit": "c0ffee", "model_version": "0.1.1-elo",
        "upstream_commit": "ac8be9c"}


@pytest.fixture(scope="module")
def report() -> Report:
    w = world(promoted=frozenset({3}))
    w.hashes = {"outputs/elo_ratings.csv": "a" * 64, f"data/external/beyondelo/{S1}.parquet":
                "b" * 64}
    w.meta_upstream_commit = "6df7a43"
    r = run_check(settings(), w)
    return render(r, INFO, w), r


def test_the_report_gives_the_verdict_with_both_conditions_figures(report: Report) -> None:
    text, r = report
    v = r["verdict"]
    assert "## Verdict" in text and "Not a poor Elo rating" in text
    for x in (v["mean"], v["sd"], v["se"], v["threshold"]):
        assert f"{x:.6f}" in text
    assert f"| {v['n']} |" in text
    assert f"{v['ours']:.6f}" in text and f"{v['baseline']:.6f}" in text


def test_a_poor_verdict_names_the_condition_that_fired(report: Report) -> None:
    _, r = report
    poor = {**r, "verdict": {**r["verdict"], "not_below_baseline": True, "poor": True}}
    text = render(poor, INFO, world())
    assert "**Poor Elo rating**" in text and "| 2. Our log-loss isn't below" in text
    assert "| yes |" in text


def test_the_report_has_both_log_loss_tables_and_the_promoted_clubs(report: Report) -> None:
    text, r = report
    assert "### All scored matches" in text
    assert "### Without matches involving a promoted club" in text
    for t in r["log_loss"].values():
        for row in t.itertuples():
            assert f"| {row.window} | {row.n} | {row.ours:.4f} | {row.beyondelo:.4f} |" in text
    assert f"{S1}: none" in text and f"{S2}: Club03" in text


def test_the_report_lists_each_fit_with_its_n(report: Report) -> None:
    text, r = report
    for name, label in (("ours", "Ours"), ("beyondelo", "beyondELO"), ("baseline", "Baseline")):
        f = r["fits"][name]
        assert f"| {label} | {f.n} | {f.slope:.6g} | {f.cut_away_draw:.6f} |" in text


def test_the_report_has_ranking_agreement_per_gameweek_and_the_disagreements(
        report: Report) -> None:
    text, r = report
    for x in r["ranking"]:
        assert f"### {x['window']}" in text
        assert f"median {x['median']:.3f}, minimum {x['min']:.3f}" in text
        for row in x["by_gw"].itertuples():
            assert f"| {row.gw} | {row.n} | {row.spearman:.3f} |" in text
        assert f"rank disagreements at GW{x['last_gw']}" in text
        assert x["disagreements"].team.iloc[0] in text


def test_the_report_has_the_counts_provenance_and_credit(report: Report) -> None:
    text, r = report
    for c in r["counts"].values():
        assert (f"| {c['matches']} | {c['finished_result']} | {c['our_rating']} | "
                f"{c['beyondelo_rating']} | {c['complete']} |") in text
    for v in ("c0ffee", "0.1.1-elo", "ac8be9c", "6df7a43", "a" * 64, "b" * 64):
        assert v in text
    assert "beyondELO (https://beyondelo.com)" in text and "CC BY 4.0" in text


def test_a_second_run_on_the_same_day_never_overwrites_the_first(tmp_path: Path) -> None:
    first = run(settings(), world(), INFO, tmp_path)
    second = run(settings(), world(), INFO, tmp_path)
    assert first.name == "2026-11-17-beyondelo.md"
    assert second.name == "2026-11-17-beyondelo-2.md"
    assert "# Outside-source Elo check" in first.read_text(encoding="utf-8")


def test_an_empty_publish_commit_shows_as_empty_not_nan() -> None:
    w = world()
    w.meta_upstream_commit = ""
    text = render(run_check(settings(), w), INFO, w)
    [row] = [ln for ln in text.splitlines() if "upstream_commit in outputs/meta.csv" in ln]
    assert row.endswith("| (empty) |") and "nan" not in row
