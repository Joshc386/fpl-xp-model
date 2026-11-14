"""The leakage, skipped-reads and concerns sections of the Elo check report."""

from __future__ import annotations

from collections import Counter

import pandas as pd

from backtest.md import fmt, table

# A log-linear fit this close is exact up to floating point: brief 6.2's claim holds.
EXACT = 1e-6


def perturbation_lines(leak: dict) -> list[str]:
    rows = []
    for c in leak["after"]:
        f = c["functions"]
        honest = f["elo_ratings"]["changed"] == f["elo_goals"]["changed"] == 0
        rows.append([f"{c['season']} as-of {c['as_of']}", c["corrupted_cells"],
                     f"{f['elo_ratings']['changed']} of {f['elo_ratings']['rows']} rows' values",
                     f"{f['elo_goals']['changed']} of {f['elo_goals']['rows']} rows' values",
                     honest, f"{f['planted_leak']['changed']} values changed",
                     f["planted_leak"]["changed"] > 0])
    return ["### Perturbation test\n",
            "Every result after the as-of gameweek corrupted in a scratch copy of the upstream "
            "folders (scores, `finished`, upstream Elo, xG and npxG; cup ties from the next "
            "deadline on too), schedule kept; both functions re-run and every output value "
            "compared with the run on the clean copy. The planted leak is a wrapper of "
            "`elo_goals` that nudges its rates by the next gameweek's goals.\n",
            table(["Case", "Cells corrupted", "elo_ratings changed", "elo_goals changed",
                   "Result", "Planted leak", "Leak caught"], rows)]


def within_lines(leak: dict) -> list[str]:
    rows = [[f"{w['season']} GW{w['gw']}", w["split"], w["corrupted_cells"], w["checked"],
             w["changed"], f"{w['control_changed']} of {w['control_rows']}",
             w["changed"] == 0 and w["control_changed"] > 0] for w in leak["within"]]
    return ["\n### Within a gameweek\n",
            "At as-of g, the GW g results kicking off at or after the middle kickoff (and "
            "everything later) were corrupted with `finished` kept. `elo_before` at every "
            "kickoff up to the split, and `elo_after` before it, must not change. The control "
            "counts GW g rows from the split on whose `elo_after` changed.\n",
            table(["Case", "Split kickoff", "Cells corrupted", "Rows checked", "Changed",
                   "Control: elo_after changed", "Result"], rows)]


def stability_lines(stability: dict) -> list[str]:
    rows = [[x, v["reads"], v["rows"], v["changed"], v["missing"], v["extra"], v["max_abs_diff"],
             v["changed"] == v["missing"] == v["extra"] == 0] for x, v in stability.items()]
    return ["\n### Every later as-of read\n",
            "Each `elo_ratings(season, g)` read compared with the season's last read: it must "
            "hold exactly the rows up to GW g, with identical `elo_before` and `elo_after`.\n",
            table(["Season", "Reads", "Rows", "Changed", "Missing", "Extra", "Max abs diff",
                   "Result"], rows, 6)]


def claims_lines(claims: pd.DataFrame) -> list[str]:
    coef = claims[["intercept", "gap", "home"]]
    steps = int((coef.diff().abs().max(axis=1).iloc[1:] > 0).sum()) if len(coef) else 0
    rows = [["As-of reads checked", len(claims)],
            ["Max residual of log lambda_for on (1, gap, home)", f"{claims.max_resid.max():.2e}"],
            ["Max abs(p_cs - exp(-lambda_against))", f"{claims.p_cs_err.max():.2e}"],
            ["Max abs(lambda_against - opponent's lambda_for)", f"{claims.mirror_err.max():.2e}"],
            ["Rows with a club with no current rating", int(claims.unrated.sum())],
            ["Implied intercept, range",
             f"{coef.intercept.min():.4f} to {coef.intercept.max():.4f}"],
            ["Implied gap coefficient per point, range",
             f"{coef.gap.min():.6f} to {coef.gap.max():.6f}"],
            ["Implied home coefficient, range", f"{coef.home.min():.4f} to {coef.home.max():.4f}"],
            ["Consecutive as-of reads whose coefficients changed",
             f"{steps} of {max(len(coef) - 1, 0)}"]]
    return ["\n### Brief 6.2 claims, from the public outputs\n",
            "Each club's current rating is its last `elo_after` in the same as-of read; "
            "log `lambda_for` is regressed on (1, rating gap, home) for every fixture in the "
            "horizon. A zero residual means the output is the claimed Poisson on the Elo gap "
            "and home advantage, using current ratings; changing coefficients show a refit at "
            "each as-of.\n", table(["Check", "Value"], rows)]


def checklist_lines(res: dict) -> list[str]:
    met, claims = res["met"], res["claims"]
    exact = bool(len(claims)) and bool(claims.max_resid.max() < EXACT)
    rows = [
        ["Features for g use nothing after the g deadline", met["perturbation"],
         "Perturbation test above: nothing changed at any case, and the planted leak was "
         f"caught. `elo_ratings` rows that aren't league fixtures: {res['non_league_rows']}. "
         "The scratch copy held no master files, and every read on it succeeded."],
        ["Rolling windows exclude the target gameweek", met["perturbation"],
         "GW g is scored from as-of g-1; each perturbation corrupts GW g itself (the first "
         "gameweek after the as-of)."],
        ["Team ratings refitted per target gameweek", bool(met["read_stability"] and exact),
         "Ratings: each as-of read holds only matches up to it (no extra rows). Goals model: "
         "implied coefficients change between as-of reads (table above)."],
        ["Price, status and ownership from the GW g-1 snapshot", "n/a",
         "The Elo component reads no player data."],
        ["Shrinkage priors from training data only", "n/a", "No shrinkage in the Elo component."],
    ]
    return ["\n### Leakage checklist (brief section 7)\n",
            table(["Item", "Result", "Evidence"], rows)]


def leakage_section(res: dict) -> list[str]:
    leak = res["leakage"]
    return (["## Leakage\n"] + perturbation_lines(leak) + within_lines(leak)
            + stability_lines(res["stability"]) + claims_lines(res["claims"])
            + checklist_lines(res))


def skips_section(res: dict) -> list[str]:
    log = res["skips"]
    counts = Counter((s.function, s.season, s.error) for s in log.skips)
    rows = [[f, x, e, n, ", ".join(str(s.as_of) for s in log.skips
                                   if (s.function, s.season, s.error) == (f, x, e))]
            for (f, x, e), n in sorted(counts.items())]
    lines = ["## Skipped reads\n",
             f"Reads skipped because they raised by design: {len(log.skips)}; no other "
             "exception occurred (any would have stopped the run).\n",
             table(["Function", "Season", "Error", "Count", "As-of"], rows)]
    if log.unraised:
        lines.append("\nExpected to raise but didn't: "
                     + ", ".join(f"{f}({x}, {a})" for f, x, a in log.unraised) + ".")
    return lines


def auto_concerns(res: dict) -> list[str]:
    """Data-driven concerns that don't fail the gate."""
    s, out = res["settings"], []
    if res["skips"].unraised:
        out.append("Reads expected to raise returned output (see Skipped reads).")
    if len(res["claims"]) and res["claims"].max_resid.max() >= EXACT:
        out.append("The goals output is not exactly log-linear in the rating gap and home "
                   "(brief 6.2 claim; see Leakage).")
    rt = res["ratings"]
    near = rt[(rt.mark == "pass mark") & (rt.spearman < s["ratings"]["min_spearman"] + 0.03)]
    if len(near):
        out.append("Pass-mark gameweeks within 0.03 of the Spearman threshold: "
                   + ", ".join(f"GW{g} ({v:.3f})" for g, v in zip(near.gw, near.spearman,
                                                                  strict=True)) + ".")
    for name, g in res["groups"].items():
        for kind, tbl, tol in (("goals", g["goals"], s["goals"]["tolerance"]),
                               ("clean-sheet", g["cs"], s["clean_sheets"]["tolerance"])):
            big = tbl["count"] >= int(s["concern_min_count"])
            off = tbl[big & ~tbl.scored & (tbl["diff"].abs() > tol)]
            for r in off.itertuples():
                out.append(f"{name}: {kind} bin {r.bin} is off by {fmt(r.diff)} on "
                           f"{r.count} team-fixtures (below the count that carries a mark).")
        if not g["beats_baseline"]:
            out.append(f"{name}: the model's log-loss is above the baseline's.")
    return out
