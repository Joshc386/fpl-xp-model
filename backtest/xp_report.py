"""The xP backtest report (markdown), in the model-validator's report format."""

from __future__ import annotations

import pandas as pd

from backtest.md import fmt, table
from backtest.xp_report_parts import (
    DEFINITIONS,
    checklist,
    control_summary,
    corrupted_files,
    counts_table,
    perturbation_table,
    timing_method,
    timing_table,
)

LABEL = {"ep_next": "ep_next", "last5": "last-5 average", "ppg": "season PPG", "model": "model"}


def _headline(h: pd.DataFrame) -> str:
    rows = [[LABEL[r.predictor], r.n, r.gameweeks, r.mae, r.rmse,
             "-" if pd.isna(r.beats_ep_next) else f"{r.beats_ep_next:.1%}"]
            for r in h.itertuples()]
    return table(["Predictor", "Rows", "Gameweeks", "MAE", "RMSE", "Gameweeks beating ep_next"],
                 rows)


def _windows(summary: dict) -> str:
    rows = [[w, LABEL[r.predictor], r.n, r.mae, r.rmse,
             "-" if pd.isna(r.beats_ep_next) else f"{r.beats_ep_next:.1%}"]
            for w, v in summary.items() if w != "all" for r in v["headline"].itertuples()]
    return table(["Window", "Predictor", "Rows", "MAE", "RMSE", "Gameweeks beating ep_next"],
                 rows)


def _gate(gate: dict, s: dict) -> str:
    g = s["gate"]
    rows = [[LABEL[p], v["mae"], v["mae_ep_next"], v["mae_below_ep_next"],
             f"{v['beats_share']:.1%}", v["share_ok"], v["calibration_ok"],
             ", ".join(v["calibration_failed_bins"]) or "none", v["leakage_ok"], v["passed"]]
            for p, v in gate.items()]
    return (f"Acceptance gate, **dry run on the development window** (the gate is decided only "
            f"on the holdout). Criteria: MAE below ep_next's; at least {g['beat_share']:.0%} of "
            f"gameweeks beating ep_next; every calibration bin with at least "
            f"{g['calibration_min_count']} rows within ±{g['calibration_tolerance']}; every "
            "leakage check passed.\n\n" + table(
                ["Candidate", "MAE", "ep_next MAE", "MAE below", "Gameweeks beating",
                 "Share met", "Calibration met", "Bins outside", "Leakage met", "Dry run"],
                rows))


def _calibration(summary: dict, preds: list[str]) -> str:
    out = []
    for p in preds:
        cal = summary["all"]["calibration"][p]
        out.append(f"{LABEL[p]}:\n\n" + table(
            ["xP bin", "Count", "Mean predicted", "Mean actual", "Actual - predicted"],
            cal[["bin", "count", "mean_pred", "mean_actual", "diff"]].values.tolist()))
    return "\n\n".join(out)


def _ranking(summary: dict, preds: list[str], s: dict) -> str:
    rows, top = [], []
    for p in preds:
        sp, hit = summary["all"]["ranking"][p]
        rows += [[LABEL[p], r.position, r.mean, r.median, r.min, r.gameweeks, r.undefined]
                 for r in sp.itertuples()]
        top.append([LABEL[p], hit])
    return ("Spearman rank correlation of prediction and actual points, per position per "
            "gameweek, summarised over gameweeks (a gameweek whose predictions are all equal "
            "has none and is counted as undefined):\n\n"
            + table(["Predictor", "Position", "Mean", "Median", "Min", "Gameweeks",
                     "Undefined"], rows)
            + f"\n\nTop-{s['metrics']['top_n']} hit rate (share of the predicted top "
            f"{s['metrics']['top_n']} who finish in the actual top {s['metrics']['top_n']}, "
            "ties at the cut counted; mean over gameweeks):\n\n"
            + table(["Predictor", "Hit rate"], top))


def _components(res: dict) -> str:
    out = []
    for name in res["component_names"]:
        got = res["components"].get(name)
        if got is None:
            out.append(f"- **{name}:** not built yet (or skipped in a baselines-only run): "
                       "nothing to score.")
            continue
        text = f"- **{name}:** {len(got['rows'])} rows.\n\n"
        if "summary" in got:
            text += ("Brier score of p_60 against the simple baseline (share of the last 5 "
                     "club-fixture gameweeks with 60+ FPL minutes per fixture, 0 when injured, "
                     "suspended, unavailable or not in the squad), no pass mark:\n\n"
                     + table(["Group", "Rows", "Brier", "Brier (baseline)", "Mean p_60",
                              "Observed 60+ rate"], got["summary"].values.tolist()) + "\n\n")
        text += table(["Bin", "Count", "Mean predicted", "Mean actual", "Actual - predicted"],
                      got["bins"].values.tolist())
        out.append(text)
    return "\n\n".join(out)


def _leakage(res: dict) -> str:
    leak, met = res["leakage"], res["leakage_met"]
    static = "\n".join(f"  - `{f}`" for f in leak["static"]) or "  - none"
    refit = "; ".join(f"{x}: {v['pairs']} pairs, frozen {v['frozen'] or 'none'}"
                      for x, v in res["refit"].items()) or "no model under test"
    return "\n\n".join([
        checklist(met, "model" in res["predictors"], _late(res["timing"])),
        table(["Criterion", "Result"], [[k, v] for k, v in met.items()]),
        "**Perturbation test.** At each case, every row dated after the as-of snapshot is "
        "corrupted in a scratch copy (results, and every non-key column of every file the "
        "loader reads), and each function is re-run; any change is a leak. The control "
        "corrupts everything up to the as-of instead (clubs kept): an honest function must "
        "change. `planted_leak` peeks at the target gameweek's points and must be caught.",
        perturbation_table(leak["cases"]) + "\n\n" + control_summary(leak["cases"]),
        "Cells corrupted per file (after the as-of):\n\n" + corrupted_files(leak["cases"]),
        f"**Static reads** ({len(leak['static_paths'])} model files scanned):\n{static}",
        f"**Refit:** {refit}.",
        timing_method(res["deadline_offset_minutes"]), timing_table(res["timing"]),
    ])


def _late(tm: pd.DataFrame) -> list[str]:
    return [f"{r.season} GW{r.snapshot}" for r in tm[tm.late].itertuples()] if len(tm) else []


def _weakest(res: dict) -> str:
    rows = [[LABEL[p], r.dimension, r.group, r.n, r.mae, r.mae_ep_next]
            for p, w in res["weakest"].items() for r in w.itertuples()]
    return table(["Predictor", "Dimension", "Group", "Rows", "MAE", "ep_next MAE"], rows)


def _concerns(res: dict) -> list[str]:
    out = []
    tm = res["timing"]
    for r in tm[tm.late].itertuples() if not tm.empty else []:
        out.append(f"{r.season} GW{r.snapshot} snapshot (predicting GW{r.target}) is late: "
                   f"its ep_next best matches the snapshot for GW{fmt(r.refers_to)} "
                   f"(share {fmt(r.refers_share, 3)}). {r.note}".rstrip())
    n = res["counts"][["not_in_snapshot", "no_actual_row", "ambiguous", "ep_next_null"]].sum()
    if n.any():
        out.append("Evaluation-set edge cases over the window: " + ", ".join(
            f"{k} {int(v)}" for k, v in n.items()))
    for x in res["skips"].unraised:
        out.append(f"{x[0]}({x[1]} as-of {x[2]}) was expected to raise and didn't")
    return out


def render(res: dict, info: dict) -> str:
    """The report for a `run_backtest.run` result and `provenance.run_info` (+ `date`)."""
    s, preds, summary = res["settings"], res["predictors"], res["summary"]
    holdout = [x["id"] for x in s["seasons"] if x["id"] in s["holdout_seasons"]]
    if "model" not in preds:
        verdict = "none, harness build (baselines only, development window)."
    elif not holdout:
        verdict = (f"none: development window only. Gate dry run "
                   f"{'met' if res['gate']['model']['passed'] else 'not met'}.")
    else:
        verdict = f"{'PASS' if res['gate']['model']['passed'] else 'FAIL'} on {holdout}."
    windows_text = ", ".join(f"{x['id']} GW{x['target_gameweeks'][0]}-"
                             f"{x['target_gameweeks'][1]}" for x in s["seasons"])
    early = [w for w in summary if w.startswith("GW") and not w.endswith("+")]
    concerns = _concerns(res)
    return "\n\n".join([
        f"# xP backtest, {info['date']}",
        f"**Verdict:** {verdict}",
        "**Code under test:**\n\n" + table(["Item", "Value"], [[k, v] for k, v in info.items()])
        + f"\n\nWindow: {windows_text}. Mode: {s['mode']}.",
        "**Headline results:**\n\n" + DEFINITIONS + "\n" + counts_table(res["counts"])
        + "\n\n" + _headline(summary["all"]["headline"]) + "\n\nBy window (late snapshots "
        "are the target gameweeks whose GW g-1 snapshot was written after the g deadline; "
        "see Leakage):\n\n" + _windows(summary) + "\n\n" + _gate(res["gate"], s),
        "**Calibration:** mean predicted against mean actual per xP bin, all target "
        "gameweeks.\n\n" + _calibration(summary, preds),
        "**Ranking:**\n\n" + _ranking(summary, preds, s),
        "**Component checks:** diagnostics with no pass mark (phase 2 plan point 1).\n\n"
        + _components(res),
        "**Leakage:**\n\n" + _leakage(res),
        "**Early season:**\n\n" + ("\n\n".join(
            f"{w}:\n\n" + _headline(summary[w]["headline"]) for w in early) or "No rows."),
        "**Weakest areas:** the groups (position, price band, FPL minutes over the last "
        f"{s['weakest']['minutes_window']} club-fixture gameweeks) with the largest MAE, of at "
        f"least {s['weakest']['min_rows']} rows.\n\n" + _weakest(res),
        "**Concerns:**\n\n" + ("\n".join(f"- {c}" for c in concerns) or "None"),
        "**Open questions and blockers:**\n\n- Player fields (status, chance of playing, "
        "price, ep_next) for 2025/26 and 2026/27 are to come from task 3's pre-deadline view "
        "(decided 2026-11-24). Until it is wired in, `xp_inputs.pre_deadline_view` reads the "
        f"GW g-1 snapshot (`player_fields: {s['player_fields']}`) and refuses a holdout "
        "season, so this run's late snapshots stay in and are reported separately.",
    ]) + "\n"
