"""Markdown report of the Elo component check (backtest/reports/{date}.md)."""

from __future__ import annotations

import pandas as pd

from backtest.elo_report_leak import auto_concerns, leakage_section, skips_section
from backtest.elo_summary import CRITERIA, weakest_bins, weakest_clubs, weakest_gameweeks
from backtest.md import table

LABELS = {
    "ratings": "Ratings track upstream Elo (Spearman >= {min_sp} at {sp_gws})",
    "goals": "Goals calibrated (within {g_tol} in every bin with >= {n} team-fixtures)",
    "clean_sheets": "Clean sheets calibrated (within {cs_pp} pp in every bin with >= {n})",
    "log_loss": "Lower Poisson log-loss than the league-average home/away baseline",
    "perturbation": "Perturbation test: no output value changes",
    "planted_leak_caught": "Positive control: the planted leak is caught at every case",
    "within_gameweek": "Within a gameweek: elo_before ignores its own and later results",
    "read_stability": "elo_before at a kickoff unchanged across every later as-of read",
}


def calib_table(t: pd.DataFrame, nd: int = 3) -> str:
    """A calibration table: every bin, with its count, means, gap and result."""
    rows = [[r.bin, r.count, r.mean_pred, r.mean_actual, r.diff,
             r.passed if r.scored else "no mark (< min count)" if r.count else "empty"]
            for r in t.itertuples()]
    return table(["Bin", "Team-fixtures", "Mean predicted", "Mean actual", "Actual - predicted",
                  "Result"], rows, nd)


def verdict_section(res: dict) -> list[str]:
    s = res["settings"]
    sp_gws = " and ".join(f"GW{lo}" if lo == hi else f"GW{lo}-{hi}"
                          for lo, hi in s["ratings"]["pass_gameweeks"])
    fill = {"min_sp": s["ratings"]["min_spearman"], "sp_gws": sp_gws,
            "g_tol": s["goals"]["tolerance"],
            "cs_pp": round(100 * s["clean_sheets"]["tolerance"]), "n": s["min_bin_count"]}
    head = "PASS" if res["passed"] else "FAIL"
    missed = ", ".join(res["missed"]) or "none"
    lines = [f"## Verdict\n\n**{head}.** Criteria missed: {missed}.\n"]
    lines.append(table(["Criterion", "Result"],
                       [[LABELS[c].format(**fill), res["met"][c]] for c in CRITERIA]))
    return lines


def code_section(info: dict) -> list[str]:
    rows = [["Repo commit", info["commit"]],
            ["src/fpl and config/ match that commit (tracked files)", info["code_clean"]],
            ["model_version", info["model_version"]],
            ["Upstream commit", f"{info['upstream_commit']} ({info['upstream_time']})"],
            ["config/model.yaml sha256", info["model_yaml_sha256"]],
            ["backtest/config.yaml sha256", info["settings_sha256"]],
            ["Command", "`.venv/Scripts/python -m backtest.elo_check`"]]
    return ["## Code under test\n", table(["Item", "Value"], rows)]


def ratings_section(res: dict) -> list[str]:
    rt = res["ratings"]
    marked = rt[rt.mark == "pass mark"]
    worst = marked.loc[marked.spearman.idxmin()] if len(marked) else None
    lines = ["## Ratings\n",
             f"{res['settings']['ratings']['season']}, every team-kickoff, our `elo_before` "
             "from `elo_ratings(season, g)` against upstream Elo at the same kickoff. Gap is "
             "ours minus upstream.\n"]
    if worst is not None:
        lines.append(f"Lowest Spearman among pass-mark gameweeks: {worst.spearman:.3f} at "
                     f"GW{int(worst.gw)}. Pairs: {int(rt.n.sum())}.\n")
    rows = [[r.gw, r.n, r.spearman, r.mean_gap, r.mean_abs_gap, r.mark,
             r.passed if r.passed is not None else "-"] for r in rt.itertuples()]
    lines.append(table(["GW", "Pairs", "Spearman", "Mean gap", "Mean abs gap", "Mark", "Result"],
                       rows, 3))
    return lines


def group_lines(name: str, g: dict, marks: bool) -> list[str]:
    note = "" if marks else " (reported without pass marks)"
    return [f"### {name}{note}\n",
            f"{g['n']} team-fixtures. Log-loss: model {g['nll_model']:.4f}, baseline "
            f"{g['nll_base']:.4f} (model - baseline {g['nll_model'] - g['nll_base']:+.4f}).\n",
            "Goals:\n", calib_table(g["goals"]), "\nClean sheets:\n", calib_table(g["cs"]), ""]


def pooled_sections(res: dict) -> list[str]:
    name, g = next(iter(res["groups"].items()))
    return [f"## Goals calibration\n\n{name}, every season pooled; pass marks apply. Each "
            "GW g fixture scored once, from `elo_goals(season, g-1)`; predicted is `lambda_for`, "
            "actual the club's goals.\n", calib_table(g["goals"]),
            f"\n## Clean-sheet calibration\n\n{name}, every season pooled; pass marks apply. "
            "Predicted `p_cs`; actual is 1 when "
            "the opponent scored 0.\n", calib_table(g["cs"]),
            "\n## Log-loss against the baseline\n",
            "Mean Poisson negative log-likelihood of each club's actual goals. The baseline "
            "predicts the league-average home goals for home sides and away goals for away "
            "sides, over finished league results of this season and last up to g-1.\n",
            table(["Group", "Team-fixtures", "Model", "Baseline", "Model - baseline", "Lower"],
                  [[k, v["n"], v["nll_model"], v["nll_base"], v["nll_model"] - v["nll_base"],
                    "model" if v["beats_baseline"] else "baseline"]
                   for k, v in res["groups"].items()], 4)]


def season_sections(res: dict) -> list[str]:
    items = list(res["groups"].items())[1:]
    cut = res["settings"]["pass_from_gw"]
    late = [(k, v) for k, v in items if k.endswith(f"GW{cut} on")]
    early = [(k, v) for k, v in items if not k.endswith(f"GW{cut} on")]
    lines = ["## Per season\n"]
    for k, v in late:
        lines += group_lines(k, v, marks=False)
    lines.append("## Early season\n")
    skipped = sorted({(sk.season, sk.as_of + 1) for sk in res["skips"].skips
                      if sk.function == "elo_goals"})
    lines.append("Target gameweeks with no goals prediction (skipped reads): "
                 + (", ".join(f"{x} GW{g}" for x, g in skipped) or "none") + ".\n")
    for k, v in early:
        lines += group_lines(k, v, marks=False)
    return lines


def weakest_section(res: dict) -> list[str]:
    n = int(res["settings"]["weakest"]["top_n"])
    pooled_summary = next(iter(res["groups"].values()))
    pooled = res["goals"][res["goals"].gw >= res["settings"]["pass_from_gw"]]
    rt = res["ratings"]
    marked = rt[rt.mark == "pass mark"].nsmallest(n, "spearman")
    pass_gws = set(rt.gw[rt.mark == "pass mark"])
    pr = res["pairs"][res["pairs"].gw.isin(pass_gws)]
    lines = ["## Weakest areas\n", "Pooled from GW6. Actual minus predicted.\n"]
    for title, pred, act in (("Clubs, goals for", "lambda_for", "goals_for"),
                             ("Clubs, goals against", "lambda_against", "goals_against")):
        w = weakest_clubs(pooled, pred, act, n)
        head = ["Club", "Team-fixtures", "Mean predicted", "Mean actual", "Actual - predicted"]
        lines += [f"{title}:\n", table(head, w.values.tolist()), ""]
    w = weakest_clubs(pr, "upstream_elo", "elo_before", n)
    lines += ["Clubs, rating gap on pass-mark gameweeks (ours minus upstream):\n",
              table(["Club", "Pairs", "Mean upstream", "Mean ours", "Mean gap"],
                    w.values.tolist(), 1), ""]
    g = weakest_gameweeks(pooled, n)
    lines += ["Gameweeks, model log-loss above the baseline:\n",
              table(["Season", "GW", "Team-fixtures", "Model", "Baseline", "Excess"],
                    g.values.tolist(), 4), ""]
    lines += ["Gameweeks, lowest Spearman with a pass mark:\n",
              table(["GW", "Pairs", "Spearman", "Mean gap"],
                    [[int(r.gw), int(r.n), r.spearman, r.mean_gap] for r in marked.itertuples()]),
              ""]
    b = weakest_bins(pooled_summary, n)
    lines += ["Bins furthest from calibration (pooled, any count):\n",
              table(["Kind", "Bin", "Count", "Mean predicted", "Mean actual", "Gap"],
                    b[["kind", "bin", "count", "mean_pred", "mean_actual",
                       "diff"]].values.tolist())]
    return lines


def render(res: dict, info: dict) -> str:
    """The whole report."""
    concerns = auto_concerns(res)
    parts = [f"# Elo component check, {info['date']}\n",
             "Phase 1, task 4: the model-validator's walk-forward test of the Elo ratings and "
             "the Elo goals model against brief section 7's Elo pass marks.\n",
             *verdict_section(res), "", *code_section(info), "", *ratings_section(res), "",
             *pooled_sections(res), "", *season_sections(res), *leakage_section(res), "",
             *skips_section(res), "", *weakest_section(res), "", "## Concerns\n",
             "\n".join(f"- {c}" for c in concerns) if concerns else "None", "",
             "## Open questions and blockers\n", "None", ""]
    return "\n".join(parts)
