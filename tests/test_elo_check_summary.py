"""The Elo check's summaries and verdict, on small frames with hand-computed answers."""

from __future__ import annotations

import pandas as pd
import pytest
from backtest.elo_summary import (
    group_summary,
    ratings_table,
    split_groups,
    verdict,
    weakest_clubs,
    weakest_gameweeks,
)

SETTINGS = {
    "seasons": [{"id": "A", "target_gameweeks": [1, 10]}, {"id": "B", "target_gameweeks": [1, 8]}],
    "pass_from_gw": 6, "min_bin_count": 2, "compare_decimals": 9,
    "goals": {"bin_edges": [0.0, 0.75, 1.25, 1.75], "tolerance": 0.1},
    "clean_sheets": {"bin_width": 0.1, "tolerance": 0.05},
    "ratings": {"season": "A", "min_spearman": 0.9, "pass_gameweeks": [[6, 7], [9, 9]],
                "unscored": [{"range": [1, 5], "why": "early"}, {"range": [8, 8], "why": "stuck"},
                             {"range": [10, 10], "why": "end"}]},
    "weakest": {"top_n": 2},
}


def scored(rows: list[tuple]) -> pd.DataFrame:
    cols = ["season", "gw", "team_name", "lambda_for", "goals_for", "p_cs", "clean_sheet",
            "nll_model", "nll_base"]
    return pd.DataFrame(rows, columns=cols)


DF = scored([
    ("A", 2, "X", 1.0, 1, 0.4, False, 1.0, 1.1),
    ("A", 6, "X", 1.0, 2, 0.4, False, 1.2, 1.3),
    ("A", 7, "Y", 1.0, 0, 0.45, True, 0.9, 1.0),
    ("B", 5, "Y", 0.5, 0, 0.6, True, 0.8, 0.7),
    ("B", 6, "Z", 0.5, 1, 0.6, False, 1.4, 1.2),
])


def test_split_groups_pool_gw6_on_and_split_seasons_and_early_weeks() -> None:
    g = split_groups(DF, SETTINGS)
    assert list(g) == ["Pooled, GW6 on", "A, GW6 on", "B, GW6 on", "A, GW1-5", "B, GW1-5"]
    assert [len(v) for v in g.values()] == [3, 2, 1, 1, 1]


def test_group_summary_has_both_calibrations_and_both_log_losses() -> None:
    out = group_summary(DF[DF.gw >= 6], SETTINGS)
    assert out["n"] == 3
    assert out["nll_model"] == pytest.approx((1.2 + 0.9 + 1.4) / 3)
    assert out["nll_base"] == pytest.approx((1.3 + 1.0 + 1.2) / 3)
    assert out["beats_baseline"] == (out["nll_model"] < out["nll_base"])
    goals = out["goals"].set_index("bin")
    assert goals.loc["0.75-1.25", "count"] == 2 and goals.loc["0.75-1.25", "mean_actual"] == 1.0
    cs = out["cs"].set_index("bin")
    assert cs.loc["0.4-0.5", "count"] == 2 and cs.loc["0.4-0.5", "mean_actual"] == 0.5


def pairs(gw: int, ours: list[float], theirs: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"season": "A", "gw": gw, "team_id": range(len(ours)),
                         "elo_before": ours, "upstream_elo": theirs})


def test_ratings_table_marks_only_the_pass_gameweeks() -> None:
    p = pd.concat([pairs(5, [1, 2, 3], [3, 2, 1]), pairs(6, [1, 2, 3], [1, 2, 3]),
                   pairs(7, [1, 2, 3], [1, 3, 2]), pairs(8, [1, 2, 3], [3, 2, 1])])
    t = ratings_table(p, SETTINGS).set_index("gw")
    assert t.loc[5, "mark"] == "no pass mark: early" and pd.isna(t.loc[5, "passed"])
    assert t.loc[6, "mark"] == "pass mark" and t.loc[6, "passed"] is True
    assert t.loc[7, "spearman"] == pytest.approx(0.5) and t.loc[7, "passed"] is False
    assert t.loc[8, "mark"] == "no pass mark: stuck"


def criteria(**over: bool) -> dict:
    base = {"ratings": True, "goals": True, "clean_sheets": True, "log_loss": True,
            "perturbation": True, "planted_leak_caught": True, "within_gameweek": True,
            "read_stability": True}
    return base | over


def test_verdict_passes_only_when_every_criterion_is_met() -> None:
    ok, missed = verdict(criteria())
    assert ok and missed == []
    ok, missed = verdict(criteria(goals=False, perturbation=False))
    assert not ok and missed == ["goals", "perturbation"]


def test_a_planted_leak_that_is_not_caught_fails_the_verdict() -> None:
    assert verdict(criteria(planted_leak_caught=False)) == (False, ["planted_leak_caught"])


def test_weakest_clubs_rank_by_the_largest_mean_error() -> None:
    # Actual minus predicted: Y -0.75 over 2, X +0.5 over 2, Z +0.5 over 1 (ties: more rows first).
    out = weakest_clubs(DF, "lambda_for", "goals_for", top_n=2)
    assert out.team_name.tolist() == ["Y", "X"]
    assert out["count"].tolist() == [2, 2] and out["diff"].tolist() == pytest.approx([-0.75, 0.5])
    out3 = weakest_clubs(DF, "lambda_for", "goals_for", top_n=3)
    assert out3.team_name.tolist() == ["Y", "X", "Z"]


def test_weakest_gameweeks_rank_by_model_minus_baseline_log_loss() -> None:
    out = weakest_gameweeks(DF, top_n=2)
    assert list(zip(out.season, out.gw, strict=True)) == [("B", 6), ("B", 5)]
    assert out.excess.tolist() == pytest.approx([0.2, 0.1])
