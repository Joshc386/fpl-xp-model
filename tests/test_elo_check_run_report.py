"""The refit and home-share parts of the Elo check's report, rendered from the honest run
(the session fixture `honest_run`, conftest.py) with hand-set changes."""

from __future__ import annotations

import copy

import pandas as pd
from backtest.elo_data import REFIT_COLUMNS
from backtest.elo_report import render

from elo_check_runs import INFO, SEASON, checklist_row


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


def mixed_refit(honest: dict) -> dict:
    """The honest run with five hand-set refit pairs: (pool changed, coefficients changed, max
    diff) of (yes, yes, 3e-3), (yes, yes, 5e-4), (yes, no, 4e-10), (no, no, 2e-15) and (no, no,
    7e-15). Two unchanged-pool pairs, so their smallest and largest differ."""
    res = copy.deepcopy(honest)
    rows = [(True, True, 3e-3), (True, True, 5e-4), (True, False, 4e-10), (False, False, 2e-15),
            (False, False, 7e-15)]
    res["refit"] = pd.DataFrame(
        [[SEASON, a, SEASON, a + 1, p, d, c, p == c] for a, (p, c, d) in enumerate(rows, 15)],
        columns=REFIT_COLUMNS)
    return res


def test_the_refit_numbers_count_the_right_pairs(honest: dict) -> None:
    text = render(mixed_refit(honest), INFO)
    assert "| Consecutive as-of pairs: pool changed / coefficients changed | 3 / 2 of 5 |" in text
    # Over the pool-changed pairs only, not all five (L04).
    assert "| Smallest coefficient change where the pool changed | 4.00e-10 |" in text
    # The largest of the unchanged-pool pairs, as a number, not "-" (L06).
    assert "| Largest coefficient change where the pool was unchanged | 7.00e-15 |" in text
    row = checklist_row(text, "Team ratings refitted")  # pool changes, not coefficient ones (L05)
    assert "pool changed at 3 and the coefficients (by more than 1e-09) at 2." in row


def test_a_non_finite_pair_is_named_and_never_hidden(honest: dict) -> None:
    """A NaN or infinite difference fails its pair (`refit_pairs`); the report says so, and
    neither the counts nor the smallest and largest steps leave it out."""
    res = copy.deepcopy(honest)
    nan, inf = float("nan"), float("inf")
    rows = [(True, True, 3e-3, True), (True, False, nan, False), (False, True, inf, False),
            (False, False, 2e-15, True)]
    res["refit"] = pd.DataFrame(
        [[SEASON, a, SEASON, a + 1, p, d, c, ok] for a, (p, c, d, ok) in enumerate(rows, 15)],
        columns=REFIT_COLUMNS)
    res["met"]["refit"], res["passed"], res["missed"] = False, False, ["refit"]
    text = render(res, INFO)
    row = checklist_row(text, "Team ratings refitted")
    for a, pool in ((16, "changed"), (17, "unchanged")):
        assert (f"{SEASON} as-of {a} to {SEASON} as-of {a + 1} (pool {pool}, coefficients "
                "not finite, max diff") in row
    assert "not finite at 2" in row
    assert ("| Consecutive as-of pairs: pool changed / coefficients changed | 2 / 2 of 4; "
            "2 not finite |") in text
    assert "| Smallest coefficient change where the pool changed | not finite |" in text
    assert "| Largest coefficient change where the pool was unchanged | not finite |" in text


# --- the home-share Concern --------------------------------------------------------------

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
    run = with_home_share(honest, [nan, 0.5, 1.0])
    share = run["goal_checks"].home_above
    n, k = int((share < 0.9).sum()), int(share.notna().sum())
    assert 0 < n < k < len(share)  # the count of reads is over the reads with a share
    mixed = concerns(run)
    assert "home rows" in mixed and "0.500" in mixed
    assert f"({n} of {k} reads below it)" in mixed  # H02


def test_the_home_share_concern_follows_its_setting(honest: dict) -> None:  # H03
    run = with_home_share(honest, [1.0, 0.7])
    run["settings"]["concern_home_share"] = 0.6
    assert "home rows" not in concerns(run)
    assert "lowest share (Concern below 0.6) | 0.700 |" in render(run, INFO)
    run["goal_checks"].loc[run["goal_checks"].index[1], "home_above"] = 0.55
    assert "0.550" in concerns(run) and "below 0.6 (1 of" in concerns(run)
