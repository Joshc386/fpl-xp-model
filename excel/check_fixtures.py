"""Checks for the Fixture Analysis sheet: both views at horizons 1, 3 and 5, against the CSV.

Each scenario sets `in_horizon` and `in_fixture_view`, recalculates, and compares the visible
grid with an independent pandas build from the CSVs: club order, headers, every cell's text,
every total and every number on Data_Grid. It also reads the colour Excel actually shows, to
prove colour follows the view, and checks the guard messages for a bad horizon.
The visible layout and the labels are written out here by hand, not taken from the builder.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

import wb_style as st
from check_workbook import TOLERANCE, CheckResult, error_cells, read_csv
from wb_fixtures import C_NUM, GRID_GWS, GRID_SHEET, letter

SHEET = "Fixture Analysis"
DASH = "–"
HEADER_ROW, FIRST_ROW, LAST_ROW = 5, 6, 25
TOTAL_COL, GW_COL, GUARD_CELL = 2, 3, (4, 5)
HORIZONS = (1, 3, 5)
VIEW_COLUMN = {"Attack": "lambda_for", "Defence": "p_cs"}
DEFAULT_HORIZON, DEFAULT_VIEW = 5, "Attack"
# team -> (texts, values, total, per-match averages)
Grid = dict[str, tuple[list[str], list[float | None], float, list[float | None]]]


def expected_grid(
    fix: pd.DataFrame, teams: list[str], next_gw: int, view: str, horizon: int
) -> Grid:
    """Per club (A-Z): each gameweek's text, summed value and per-match average; the total."""
    column = VIEW_COLUMN[view]
    out: Grid = {}
    for team in teams:
        texts: list[str] = []
        values: list[float | None] = []
        averages: list[float | None] = []
        for k in range(GRID_GWS):
            rows = fix[(fix["team"] == team) & (fix["gw"] == str(next_gw + k))]
            if k >= horizon:
                texts.append("")
                values.append(None)
                averages.append(None)
            elif rows.empty:
                texts.append(DASH)
                values.append(None)
                averages.append(None)
            else:
                value = sum(float(v) for v in rows[column])
                sides = ["H" if h == "True" else "A" for h in rows["home"]]
                text = " + ".join(
                    f"{o} ({s})" for o, s in zip(rows["opponent"], sides, strict=True)
                )
                texts.append(text + (f" = {value:.2f}" if len(rows) > 1 else ""))
                values.append(value)
                averages.append(value / len(rows))
        out[team] = (texts, values, sum(v for v in values if v is not None), averages)
    return out


def _compare(
    label: str, want: Grid, shown: tuple, numbers: tuple, teams: list[str], result: CheckResult
) -> int:
    """Club order, texts, totals and Data_Grid numbers against the expected grid."""
    fail = result.failures
    order = sorted(teams, key=lambda t: -want[t][2])  # stable: ties stay A-Z
    if [row[0] for row in shown] != order:
        fail.append(f"{SHEET} [{label}]: club order {[r[0] for r in shown]} != {order}")
    by_team = {row[0]: row for row in shown}
    compared = 0
    for team, (texts, _values, total, _avgs) in want.items():
        row = by_team.get(team)
        if row is None:
            fail.append(f"{SHEET} [{label}]: {team} missing")
            continue
        compared += GRID_GWS + 1
        got = list(row[GW_COL - 1 : GW_COL - 1 + GRID_GWS])
        if got != texts:
            fail.append(f"{SHEET} [{label}] {team}: {got} != {texts}")
        if abs(row[1] - total) > TOLERANCE:
            fail.append(f"{SHEET} [{label}] {team}: total {row[1]} != {total:.4f}")
    for i, team in enumerate(sorted(teams)):  # Data_Grid holds the clubs A-Z
        for k in range(GRID_GWS):
            cell, value = numbers[i][k], want[team][1][k]
            compared += 1
            same = (
                (cell == "") if value is None else (cell != "" and abs(cell - value) <= TOLERANCE)
            )
            if not same:
                fail.append(f"Data_Grid [{label}] {team} GW{k + 1}: Excel {cell!r}, CSV {value!r}")
    return compared


def _check_headers(label: str, ws: Any, next_gw: int, horizon: int, result: CheckResult) -> None:
    """Club, Total, then `GW {next_gw + k}` for each gameweek in the horizon and empty after."""
    want = ["Club", "Total"] + [f"GW {next_gw + k}" if k < horizon else "" for k in range(GRID_GWS)]
    got = [ws.Cells(HEADER_ROW, c).Value2 for c in range(1, len(want) + 1)]
    got = ["" if g is None else g for g in got]
    if got != want:
        result.failures.append(f"{SHEET} [{label}]: headers {got} != {want}")


def _shown_colour(ws: Any, row: int, col: int) -> int:
    return int(ws.Cells(row, col).DisplayFormat.Interior.Color)


def _check_colours(label: str, ws: Any, want: Grid, shown: tuple, result: CheckResult) -> None:
    """Colours Excel shows. Cells: scale step of the per-match average (a dash is grey).
    Total column: highest total at the top of the scale, lowest at the bottom."""
    row_of = {row[0]: FIRST_ROW + i for i, row in enumerate(shown)}
    cells = [
        (avg, team, k) for team, v in want.items() for k, avg in enumerate(v[3]) if avg is not None
    ]
    if cells and max(cells)[0] > min(cells)[0]:
        lo, hi = min(cells)[0], max(cells)[0]
        for avg, team, k in cells:
            raw = st.SCALE_STEPS * (avg - lo) / (hi - lo)
            if abs(raw - int(raw) - 0.5) < 1e-6:
                continue  # a tie between two steps: Excel and Python may round differently
            got = _shown_colour(ws, row_of[team], GW_COL + k)
            if got != st.rgb(st.scale_colour(round(raw))):
                result.failures.append(
                    f"{SHEET} [{label}] {team} GW{k + 1}: colour {got}, step {round(raw)}"
                )
    for team, v in want.items():
        for k, text in enumerate(v[0]):
            if text == DASH and _shown_colour(ws, row_of[team], GW_COL + k) != st.rgb(st.GREY_DASH):
                result.failures.append(f"{SHEET} [{label}] {team} GW{k + 1}: dash is not grey")
    totals = [v[2] for v in want.values()]
    if max(totals) > min(totals):
        top, bottom = shown[0][0], shown[-1][0]
        for team, colour in ((top, st.SCALE_HIGH), (bottom, st.SCALE_LOW)):
            if _shown_colour(ws, row_of[team], TOTAL_COL) != st.rgb(colour):
                result.failures.append(f"{SHEET} [{label}] {team}: total colour is not {colour}")


def _check_guard(app: Any, wb: Any, ws: Any, result: CheckResult) -> None:
    """A cleared, too-large or fractional horizon shows a message and no error value."""
    cell = wb.Names("in_horizon").RefersToRange
    for value, needle in ((None, "empty"), (7, "from 1 to"), (2.5, "whole number")):
        cell.Value = value
        app.Calculate()
        shown = ws.Cells(*GUARD_CELL).Value2 or ""
        if needle not in shown:
            result.failures.append(f"{SHEET}: horizon {value!r} shows message {shown!r}")
        if error_cells(ws) or error_cells(wb.Worksheets(GRID_SHEET)):
            result.failures.append(f"{SHEET}: error values with horizon {value!r}")


def _scenario(app: Any, wb: Any, data: dict, view: str, horizon: int, result: CheckResult) -> int:
    ws, grid, teams = data["ws"], data["grid"], data["teams"]
    label = f"{view}, horizon {horizon}"
    wb.Names("in_horizon").RefersToRange.Value = horizon
    wb.Names("in_fixture_view").RefersToRange.Value = view
    app.Calculate()
    want = expected_grid(data["fix"], teams, data["next_gw"], view, horizon)
    shown = ws.Range(f"A{FIRST_ROW}:{letter(GW_COL + GRID_GWS - 1)}{LAST_ROW}").Value2
    numbers = grid.Range(f"{letter(C_NUM)}2:{letter(C_NUM + GRID_GWS - 1)}{LAST_ROW - 4}").Value2
    compared = _compare(label, want, shown, numbers, teams, result)
    _check_headers(label, ws, data["next_gw"], horizon, result)
    _check_colours(label, ws, want, shown, result)
    if (ws.Cells(*GUARD_CELL).Value2 or "") != "":
        result.failures.append(
            f"{SHEET} [{label}]: unexpected message {ws.Cells(*GUARD_CELL).Value2!r}"
        )
    texts = [t for v in want.values() for t in v[0]]
    result.grid_stats[label] = (sum(t == DASH for t in texts), sum(" + " in t for t in texts))
    if error_cells(ws) or error_cells(grid):
        result.failures.append(f"{SHEET} [{label}]: error values")
    return compared


def check_fixture_analysis(app: Any, wb: Any, base_path: str, result: CheckResult) -> None:
    """Run both views at every horizon and the guard messages; record what was compared."""
    ws = wb.Worksheets(SHEET)
    data = {
        "ws": ws,
        "grid": wb.Worksheets(GRID_SHEET),
        "fix": read_csv(base_path, "fixture_difficulty.csv"),
        "teams": sorted(set(read_csv(base_path, "players.csv")["team"])),
        "next_gw": int(read_csv(base_path, "meta.csv")["next_gw"][0]),
    }
    view_formula = wb.Names("in_fixture_view").RefersToRange.Validation.Formula1
    if view_formula != ",".join(VIEW_COLUMN):
        result.failures.append(f"{SHEET}: view dropdown is {view_formula!r}")
    total = 0
    try:
        for view in VIEW_COLUMN:
            for horizon in HORIZONS:
                total += _scenario(app, wb, data, view, horizon, result)
        _check_guard(app, wb, ws, result)
    finally:
        wb.Names("in_horizon").RefersToRange.Value = DEFAULT_HORIZON
        wb.Names("in_fixture_view").RefersToRange.Value = DEFAULT_VIEW
        app.Calculate()
    result.values_compared[SHEET] = total
