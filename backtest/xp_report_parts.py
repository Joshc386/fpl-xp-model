"""Sections of the xP backtest report that describe the method and the leakage evidence."""

from __future__ import annotations

import pandas as pd

from backtest.md import fmt, table

DEFINITIONS = """\
How each predictor is built for target gameweek g, from the as-of g-1 read only (the GW g-1
snapshot and earlier, `load_as_of(season, g-1, "backtest")`):

- **ep_next:** `dim_player.ep_next` at as-of g-1, FPL's own figure as published (it already
  covers a blank or a double). A null counts as 0.
- **last-5 average:** the player's FPL points per club fixture over his last 5 gameweeks up to
  g-1 in which his club (that gameweek's `fact_player_gw.team_id`) had a Premier League
  fixture, played or not. A blank gameweek is skipped; a double counts as one of the 5, with
  both fixtures in the denominator. Times his club's fixtures in g, so 0 in a blank and doubled
  in a double. 0 with no such gameweek.
- **season PPG:** players.csv `ppg` at as-of g-1 (season points over appearances, FPL's
  definition), times his club's fixtures in g.
- **model:** the configured `xp_backtest.model` callable at as-of g-1, its `xp_total` summed
  over the player's rows for g; no row means 0 only if his club has no fixture in g.

**Evaluation set** (brief section 7, as written): players with FPL minutes > 0 in g, or who
started one of their club's previous 3 finished Premier League matches before g (club: the
GW g-1 snapshot's; starts: `fact_player_gw` rows at that club; a double gameweek cut by the
window is resolved from match minutes, and what stays unresolved counts as started and is
counted). It uses no model's output, so every predictor is scored on identical rows. Members
missing from the GW g-1 snapshot, and members with no `fact_player_gw` row for g, can't be
scored by anyone and are counted. GW1 can't be predicted: there is no snapshot before it.
"""

CHECKLIST = [
    ("Features for gameweek g use nothing timestamped after the g deadline", "perturbation"),
    ("Rolling windows exclude the target gameweek", "perturbation"),
    ("Team ratings are refitted per target gameweek, not fitted once on the full season",
     "refit"),
    ("Price, status and ownership come from the GW g-1 snapshot, never the master files",
     "static"),
    ("Shrinkage priors are computed from training data only", "perturbation"),
]

EVIDENCE = {
    "perturbation": "every row dated after the as-of snapshot is corrupted in every file the "
                    "loader reads (GW g's folder included) and every honest output must stay "
                    "the same; the planted leak must be caught (perturbation table below)",
    "refit": "consecutive as-of reads of the model must not give identical forecasts for the "
             "gameweeks they share (the Elo goals refit is checked in the Elo component check)",
    "static": "the harness reads these only through `xp_inputs.pre_deadline_view` from the "
              "backtest read; model sources must name no reader that bypasses `load_as_of` "
              "(static reads below); the scratch copy has no master files, so a master read "
              "fails the clean run",
}


def counts_table(counts: pd.DataFrame) -> str:
    """Evaluation-set counts summed over the target gameweeks."""
    cols = ["in_set", "scored", "not_in_snapshot", "no_actual_row", "ambiguous", "ep_next_null"]
    totals = counts[cols].sum()
    return table(["Evaluation set", *cols], [["all target gameweeks", *totals.tolist()]])


def checklist(met: dict[str, bool], has_model: bool, late: list[str]) -> str:
    """The section 7 checklist with its evidence. `late` names the GW g-1 snapshots that hold
    player fields from after the g deadline (the snapshot-timing audit)."""
    rows = []
    for item, key in CHECKLIST:
        ok = met[key] and (met["planted_leak_caught"] and met["copy_reached"]
                           if key == "perturbation" else True)
        note = EVIDENCE[key]
        if key == "refit" and not has_model:
            note = "no model under test (baselines only); " + note
        if item.startswith("Features for gameweek g") and late:
            note += (f". Except: {len(late)} late snapshots ({', '.join(late)}) hold player "
                     "fields (status, chance, price, ep_next) from after the deadline; their "
                     "target gameweeks are reported separately (snapshot timing, below)")
        rows.append([item, ok, note])
    return table(["Checklist item", "Result", "Evidence"], rows)


def perturbation_table(cases: list[dict]) -> str:
    rows = []
    for c in cases:
        cells = sum(c["corrupted_cells"].values())
        for name, v in c["functions"].items():
            ctl = c["control"].get(name, {})
            rows.append([c["season"], c["as_of"], cells, name, v["rows"], fmt(v["changed"]),
                         fmt(ctl.get("changed")), ctl.get("by") or "-", v["error"] or "",
                         ctl.get("error") or ""])
    return table(["Season", "As-of", "Cells corrupted", "Function", "Rows", "Changed",
                  "Control changed", "Control changed by", "Error", "Control error"], rows)


def control_summary(cases: list[dict]) -> str:
    """How the controls changed: by value, by error (failing only on the corrupted copy), or
    not at all (the function never read the copy)."""
    by = [v.get("by") for c in cases for v in c["control"].values()]
    return (f"Controls: {by.count('value')} changed by value, {by.count('error')} by error "
            f"(the loader rejected the corrupted copy), {by.count(None)} not at all.")


def corrupted_files(cases: list[dict]) -> str:
    files = sorted({f for c in cases for f in c["corrupted_cells"]})
    rows = [[c["season"], c["as_of"], *[c["corrupted_cells"].get(f, 0) for f in files]]
            for c in cases]
    return table(["Season", "As-of", *files], rows)


def timing_table(tm: pd.DataFrame) -> str:
    if tm.empty:
        return "Not run."
    fields = [c for c in tm.columns if c.startswith("changed_")]
    rows = [[r["season"], r["snapshot"], r["target"], str(r.get("deadline", "")),
             str(r.get("last_write", "")), *[fmt(r.get(f), 3) for f in fields],
             "late" if r["late"] else "on time", fmt(r["refers_to"]),
             fmt(r["refers_share"], 3), r["note"]] for _, r in tm.iterrows()]
    return table(["Season", "Snapshot", "Target", "Deadline", "Last write",
                  *[f.removeprefix("changed_") for f in fields], "Timing", "ep_next refers to",
                  "Match share", "Note"], rows)


def timing_method(offset_minutes: int) -> str:
    """How the snapshot-timing audit works, with the configured deadline offset."""
    return TIMING_METHOD.format(offset=offset_minutes)


TIMING_METHOD = """\
**Snapshot timing method.** For each GW g-1 snapshot, `playerstats.csv` as the loader reads
it is compared with its last version committed before the GW g deadline (the first Premier
League kickoff minus {offset} minutes), from the upstream checkout's git history. Fields: ep_next,
price, status and chance of playing, as the loader reads them (price in £m, a blank chance as
100). A snapshot is **late** when more than `late_share` of players differ in any field, or no
version predates the deadline. "ep_next refers to" is the target gameweek of the pre-deadline
snapshot whose ep_next the read version matches best. Results for target gameweeks with a
late snapshot are reported separately. This is a timing audit read from git, never a
predictor input."""
