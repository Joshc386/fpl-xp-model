"""The leakage, skipped-reads and concerns sections of the Elo check report."""

from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd

from backtest.elo_summary import group_label
from backtest.md import fmt, table

HONEST = ("elo_ratings", "elo_goals")


def perturbation_lines(leak: dict) -> list[str]:
    """One row per perturbation case: changes, the planted leak and the copy control."""
    rows = []
    for c in leak["after"]:
        f, ctl = c["functions"], c["control"]
        rows.append([f"{c['season']} as-of {c['as_of']}", c["corrupted_cells"],
                     *(f"{f[n]['changed']} of {f[n]['rows']} rows' values" for n in HONEST),
                     all(f[n]["changed"] == 0 for n in HONEST),
                     f"{f['planted_leak']['changed']} changed", f["planted_leak"]["changed"] > 0,
                     " / ".join(str(ctl[n]["changed"]) for n in HONEST),
                     all(ctl[n]["changed"] > 0 for n in HONEST)])
    return ["### Perturbation test\n",
            "Every result after the as-of gameweek corrupted in a scratch copy of the upstream "
            "folders, in `matches.csv` and `fixtures.csv` (scores, `finished`, upstream Elo, xG "
            "and npxG; cup ties from the next deadline on too), schedule kept; both functions "
            "re-run and every output value compared with the run on the clean copy. The planted "
            "leak is a wrapper of `elo_goals` that nudges its rates by the next gameweek's "
            "goals. The copy control instead corrupts every league result up to the as-of "
            "(`finished` kept): both functions' output must change, which shows each reads the "
            "copy.\n",
            table(["Case", "Cells corrupted", "elo_ratings changed", "elo_goals changed",
                   "Result", "Planted leak", "Leak caught", "Copy control: ratings / goals",
                   "Copy reached"], rows)]


def within_lines(leak: dict) -> list[str]:
    """One row per within-gameweek case."""
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
    """One row per season: every as-of read of `elo_ratings` against the last one."""
    rows = [[x, v["reads"], v["rows"], v["changed"], v["missing"], v["extra"], v["max_abs_diff"],
             v["changed"] == v["missing"] == v["extra"] == 0] for x, v in stability.items()]
    return ["\n### Every later as-of read\n",
            "Each `elo_ratings(season, g)` read compared with the season's last read: it must "
            "hold exactly the rows up to GW g, with identical `elo_before` and `elo_after`.\n",
            table(["Season", "Reads", "Rows", "Changed", "Missing", "Extra", "Max abs diff",
                   "Result"], rows, 6)]


def shape_lines(checks: pd.DataFrame, s: dict) -> list[str]:
    """Brief 6.2's shape, checked from the public outputs without assuming a form."""
    low = float(s["concern_home_share"])
    rows = [["As-of reads checked", len(checks)],
            ["Steps up in rating gap where lambda doesn't rise (home and away rows)",
             int(checks.not_rising.sum())],
            ["Equal gaps with different lambda", int(checks.tie_mismatch.sum())],
            [f"Home rows above the away curve at the same gap, lowest share (Concern below "
             f"{low:g})", fmt(float(checks.home_above.min()))],
            ["Max abs(p_cs - exp(-lambda_against)) (contract)", f"{checks.p_cs_err.max():.2e}"],
            ["Max abs(lambda_against - opponent's lambda_for)", f"{checks.mirror_err.max():.2e}"],
            ["Rows with a club with no current rating", int(checks.unrated.sum())]]
    return ["\n### The goals output's shape (brief 6.2)\n",
            "The brief says the Elo goals model is a Poisson driven by the rating gap and home "
            "advantage. Without assuming a form: within each as-of read, each club's current "
            "rating is its last `elo_after`, and for home and away rows separately, sorted by "
            "gap, lambda must rise with the gap and be equal at equal gaps. These are necessary, "
            "not sufficient: a rate that depends on anything else, such as the club, can break "
            "one of them but can also pass both. The home share has no pass mark; a lowest "
            f"share below {low:g} (reads with no comparable home gap ignored) is listed under "
            "Concerns.\n",
            table(["Check", "Value"], rows)]


def form_lines(checks: pd.DataFrame, refit: pd.DataFrame, s: dict) -> list[str]:
    """The current model's form, as information, and the coefficient steps the refit check
    compares (`elo_data.refit_pairs`)."""
    coef, tol = checks[["intercept", "gap", "home"]], float(s["refit_tolerance"])
    changed = refit.pool_changed.astype(bool)  # an empty frame's column is object dtype
    gained, same = refit[changed], refit[~changed]
    rows = [["Max residual of log lambda_for on (1, gap, home)", f"{checks.max_resid.max():.2e}"],
            ["Fitted intercept, range",
             f"{coef.intercept.min():.4f} to {coef.intercept.max():.4f}"],
            ["Fitted gap coefficient per point, range",
             f"{coef.gap.min():.6f} to {coef.gap.max():.6f}"],
            ["Fitted home coefficient, range", f"{coef.home.min():.4f} to {coef.home.max():.4f}"],
            ["Consecutive as-of pairs: pool changed / coefficients changed",
             f"{len(gained)} / {int(refit.coef_changed.sum())} of {len(refit)}"
             + (f"; {bad} not finite" if (bad := _not_finite(refit)) else "")],
            ["Smallest coefficient change where the pool changed", _step(gained.max_diff, "min")],
            ["Largest coefficient change where the pool was unchanged",
             _step(same.max_diff, "max")]]
    return ["\n### The current model's form and the refit check\n",
            "The model's form is log-linear, log lambda = a + b * gap + h * home (chosen "
            "2026-11-14); the brief doesn't require it, and the form has no pass mark. A "
            "residual near zero means the output has that form. The coefficients summarise each "
            "read's fit, and the refit criterion compares them between consecutive as-of reads, "
            "the season boundary included: their largest change must be above "
            f"{tol:g} when the fitting pool (finished league results of this season and last, "
            "up to the as-of) changed, and they must not change when the pool is identical, as "
            "after a wholly postponed gameweek.\n", table(["Check", "Value"], rows)]


def _step(diffs: pd.Series, how: str) -> str:
    """The smallest or largest coefficient change: "-" if none, "not finite" if any is NaN or
    infinite (pandas' min and max would skip a NaN)."""
    if not len(diffs):
        return "-"
    return f"{getattr(diffs, how)():.2e}" if np.isfinite(diffs).all() else "not finite"


def _not_finite(refit: pd.DataFrame) -> int:
    """Pairs whose coefficient difference is NaN or infinite (each fails, `refit_pairs`)."""
    return int((~np.isfinite(refit.max_diff.astype("float64"))).sum())


def _leak_counts(res: dict) -> dict[str, int]:
    after = res["leakage"]["after"]
    return {"cases": len(after),
            "changed": sum(c["functions"][n]["changed"] for c in after for n in HONEST),
            "caught": sum(c["functions"]["planted_leak"]["changed"] > 0 for c in after),
            "reached": sum(all(c["control"][n]["changed"] > 0 for n in HONEST) for c in after),
            "extra": sum(v["extra"] for v in res["stability"].values())}


def _failing(refit: pd.DataFrame) -> str:
    """Each pair that breaks the refit rule: both reads, and what changed."""
    def word(x: bool) -> str:
        return "changed" if x else "unchanged"

    def coef(r: tuple) -> str:
        return word(r.coef_changed) if np.isfinite(r.max_diff) else "not finite"

    return "; ".join(f"{r.from_season} as-of {r.from_as_of} to {r.to_season} as-of {r.to_as_of} "
                     f"(pool {word(r.pool_changed)}, coefficients {coef(r)}, max "
                     f"diff {r.max_diff:.2e})" for r in refit[~refit.ok].itertuples()) or "none"


def checklist_lines(res: dict) -> list[str]:
    """The section 7 checklist items that apply, each result and its evidence from the run."""
    met, k = res["met"], _leak_counts(res)
    refit, tol = res["refit"], float(res["settings"]["refit_tolerance"])
    deadline_ok = (met["perturbation"] and met["planted_leak_caught"] and met["copy_reached"]
                   and res["non_league_rows"] == 0)
    rows = [
        ["Features for g use nothing after the g deadline", deadline_ok,
         f"{k['cases']} perturbation cases: {k['changed']} output values changed; planted leak "
         f"caught in {k['caught']} of {k['cases']}; copy control reached both functions in "
         f"{k['reached']} of {k['cases']}. `elo_ratings` rows that aren't league fixtures: "
         f"{res['non_league_rows']}. The scratch copy held no master files."],
        ["Rolling windows exclude the target gameweek", met["perturbation"],
         f"GW g is scored from as-of g-1, and each of the {k['cases']} perturbation cases "
         f"corrupts the target gameweek itself; {k['changed']} output values changed."],
        ["Team ratings refitted per target gameweek",
         bool(met["read_stability"] and met["refit"]),
         f"Ratings: {k['extra']} rows from after the as-of across every read. Goals model: "
         f"{len(refit)} consecutive pairs of as-of reads (at least one needed); the fitting "
         f"pool changed at {int(refit.pool_changed.sum())} and the coefficients (by more than "
         f"{tol:g}) at {int(refit.coef_changed.sum())}"
         + (f"; the difference was not finite at {bad}" if (bad := _not_finite(refit)) else "")
         + ". Failing pairs: "
         f"{_failing(refit)}."],
        ["Price, status and ownership from the GW g-1 snapshot", "n/a",
         "The Elo component reads no player data."],
        ["Shrinkage priors from training data only", "n/a", "No shrinkage in the Elo component."],
    ]
    return ["\n### Leakage checklist (brief section 7)\n",
            table(["Item", "Result", "Evidence"], rows)]


def leakage_section(res: dict) -> list[str]:
    """The whole leakage section. With no goal checks, one line replaces shape and form."""
    leak, checks, s = res["leakage"], res["goal_checks"], res["settings"]
    goals = (shape_lines(checks, s) + form_lines(checks, res["refit"], s) if len(checks) else
             ["\nNo as-of read had both a goals and a ratings read, so there is no shape, form "
              "or refit evidence (the refit criterion needs at least one pair).\n"])
    return (["## Leakage\n"] + perturbation_lines(leak) + within_lines(leak)
            + stability_lines(res["stability"]) + goals + checklist_lines(res))


def skips_section(res: dict) -> list[str]:
    """The reads skipped by design, counted by function, season and error."""
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
    checks = res["goal_checks"]
    if len(checks) and (checks.not_rising.sum() or checks.tie_mismatch.sum()):
        out.append("The goals output doesn't depend only on the rating gap and home, or doesn't "
                   f"rise with the gap: {int(checks.not_rising.sum())} steps that don't rise and "
                   f"{int(checks.tie_mismatch.sum())} equal-gap mismatches (brief 6.2; see "
                   "Leakage).")
    share = checks.home_above.dropna() if len(checks) else pd.Series(dtype="float64")
    low = float(s["concern_home_share"])
    if len(share) and share.min() < low:
        at = checks.loc[share.idxmin()]
        out.append(f"The share of home rows above the away curve at the same gap fell to "
                   f"{share.min():.3f} at {at.season} as-of {int(at.as_of)}, below {low:g} "
                   f"({int((share < low).sum())} of {len(share)} reads below it): the home prior "
                   "may be pulling home advantage towards zero (brief 6.2; see Leakage).")
    rt, margin = res["ratings"], float(s["concern_spearman_margin"])
    near = rt[(rt.mark == "pass mark") & (rt.spearman < s["ratings"]["min_spearman"] + margin)]
    if len(near):
        out.append(f"Pass-mark gameweeks within {margin:g} of the Spearman threshold: "
                   + ", ".join(f"GW{g} ({v:.3f})" for g, v in zip(near.gw, near.spearman,
                                                                  strict=True)) + ".")
    for key, g in res["groups"].items():
        name = group_label(key, s)
        for kind, tbl in (("goals", g["goals"]), ("clean-sheet", g["cs"])):
            big = tbl["count"] >= int(s["concern_min_count"])
            off = tbl[big & ~tbl.scored & (tbl["diff"].abs() > tbl["limit"])]
            for r in off.itertuples():
                out.append(f"{name}: {kind} bin {r.bin} is off by {fmt(r.diff)} (limit "
                           f"{fmt(r.limit)}) on {r.count} team-fixtures, below the count that "
                           "carries a mark.")
        if not g["beats_baseline"]:
            out.append(f"{name}: the model's log-loss is above the baseline's.")
    return out
