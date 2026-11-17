"""Checks for the Player Database sheet: filters against the CSV, and the displayed values.

Each scenario sets the input cells, recalculates and compares the sheet's rows with the same
filter done independently in pandas on the CSV. Inputs are cleared at the end.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from check_workbook import CheckResult, _same, error_cells, read_csv

# Written out by hand, not imported from the builder, so a wrong label, source column, number
# format or dropdown in the builder is caught: (header, tbl_players column, number format, kind).
SHEET = "Player Database"
HEADER_ROW, FIRST_ROW = 6, 7
EXPECTED_COLUMNS = (
    ("Player", "web_name", "General", "plain"),
    ("Team", "team", "General", "plain"),
    ("Position", "position", "General", "plain"),
    ("Price", "price_m", '£0.0"m"', "plain"),
    ("Status", "status", "General", "plain"),
    ("News", "news", "General", "plain"),
    ("Chance of playing", "chance_next", '0.0"%"', "plain"),
    ("Ownership", "selected_pct", '0.0"%"', "plain"),
    ("Minutes", "minutes", "#,##0", "plain"),
    ("Starts", "starts", "#,##0", "plain"),
    ("Total points", "total_points", "#,##0", "plain"),
    ("Points per game", "ppg", "0.0", "plain"),
    ("xG per 90", "xg90", "0.00", "plain"),
    ("xA per 90", "xa90", "0.00", "plain"),
    ("Defensive contributions per 90", "dc90", "0.00", "plain"),
    ("Penalty taker", "pen_taker", "General", "bool"),
    ("Net transfers this GW", "net_transfers_gw", "+#,##0;-#,##0;0", "plain"),
    ("Price change this GW", "price_change_gw", '+£0.0"m";-£0.0"m";£0.0"m"', "plain"),
    ("Price change since start", "price_change_start", '+£0.0"m";-£0.0"m";£0.0"m"', "plain"),
)
INPUT_NAMES = ("in_search", "in_team", "in_position", "in_max_price", "in_status")
# input -> (dropdown name, CSV column it must list). Team and status sort A-Z; position keeps
# the CSV's first-appearance order (GKP, DEF, MID, FWD).
DROPDOWNS = {
    "in_team": ("lst_team", "team", True),
    "in_position": ("lst_position", "position", False),
    "in_status": ("lst_status", "status", True),
}

# Each scenario: label -> {input name: value}. Empty means no filters.
SCENARIOS: dict[str, dict[str, Any]] = {
    "no filters": {},
    "team ARS": {"in_team": "ARS"},
    "position MID": {"in_position": "MID"},
    "status i": {"in_status": "i"},
    "max price 6.0": {"in_max_price": 6.0},
    "ARS + MID + max 6.0": {"in_team": "ARS", "in_position": "MID", "in_max_price": 6.0},
    "search 'sa' (case-insensitive)": {"in_search": "SA"},
    "team ARS + search 'zzzz' (no match)": {"in_team": "ARS", "in_search": "zzzz"},
}


def expected_rows(csv: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
    """Rows the sheet should show: filtered like the inputs, highest total points first."""
    keep = pd.Series(True, index=csv.index)
    if "in_team" in filters:
        keep &= csv["team"] == filters["in_team"]
    if "in_position" in filters:
        keep &= csv["position"] == filters["in_position"]
    if "in_status" in filters:
        keep &= csv["status"] == filters["in_status"]
    if "in_max_price" in filters:
        keep &= csv["price_m"].astype(float) <= filters["in_max_price"]
    if "in_search" in filters:
        keep &= csv["web_name"].str.lower().str.contains(filters["in_search"].lower(), regex=False)
    out = csv[keep].copy()
    out["_pts"] = out["total_points"].astype(int)
    return out.sort_values("_pts", ascending=False, kind="stable").drop(columns="_pts")


def _flatten(values: Any) -> list[str]:
    """A value, or any nesting of tuples of values, as a flat list of text."""
    if isinstance(values, tuple):
        return [text for item in values for text in _flatten(item)]
    return [str(values)]


def check_labels_formats_dropdowns(
    app: Any, wb: Any, csv: pd.DataFrame, result: CheckResult
) -> None:
    """Headers, number formats and dropdown lists against the hand-written expectations."""
    ws = wb.Worksheets(SHEET)
    for i, (header, source, fmt, _kind) in enumerate(EXPECTED_COLUMNS, 1):
        shown = ws.Cells(HEADER_ROW, i).Value2
        if shown != header:
            result.failures.append(
                f"{SHEET} column {i} ({source}): header {shown!r}, want {header!r}"
            )
        shown_fmt = ws.Cells(FIRST_ROW, i).NumberFormat
        if shown_fmt != fmt:
            result.failures.append(f"{SHEET} {header}: format {shown_fmt!r}, want {fmt!r}")
    for input_name, (list_name, column, sort) in DROPDOWNS.items():
        unique = list(dict.fromkeys(csv[column]))
        want = sorted(unique) if sort else unique
        got = _flatten(getattr(app.Evaluate(list_name), "Value2", None))
        if got != want:
            result.failures.append(f"{SHEET} {list_name} lists {got}, want {want}")
        used = wb.Names(input_name).RefersToRange.Validation.Formula1
        if used != f"={list_name}":
            result.failures.append(
                f"{SHEET} {input_name} dropdown uses {used!r}, want ={list_name}"
            )


def _expected_text(value: str, kind: str) -> str:
    """What the sheet shows for a CSV value: a bool column shows Yes or empty."""
    return ("Yes" if value == "True" else "") if kind == "bool" else value


def _displayed(ws: Any, rows: int) -> tuple:
    """The sheet's rows as shown, `rows` of them, in the expected column order."""
    if rows == 0:
        return ()
    last = len(EXPECTED_COLUMNS)
    return ws.Range(ws.Cells(FIRST_ROW, 1), ws.Cells(FIRST_ROW + rows - 1, last)).Value2


def _spill_rows(ws: Any) -> int:
    """How many rows the first column's spill covers (0 when it shows one blank)."""
    spill = ws.Cells(FIRST_ROW, 1).SpillingToRange
    return 0 if spill is None else spill.Rows.Count


def _compare(label: str, shown: tuple, want: pd.DataFrame, result: CheckResult) -> int:
    """Compare the displayed rows with the expected rows; return the values compared."""
    compared = 0
    for r, csv_row in enumerate(want.to_dict("records")):
        for c, (_header, source, _fmt, kind) in enumerate(EXPECTED_COLUMNS):
            compared += 1
            text = _expected_text(csv_row[source], kind)
            if not _same(shown[r][c], text, source):
                result.failures.append(
                    f"Player Database [{label}] row {r + 1} {source}: "
                    f"Excel {shown[r][c]!r}, CSV {text!r}"
                )
                return compared
    return compared


def check_player_database(app: Any, wb: Any, base_path: str, result: CheckResult) -> None:
    """Run every scenario, recording counts and values compared in `result`."""
    ws = wb.Worksheets(SHEET)
    csv = read_csv(base_path, "players.csv")
    check_labels_formats_dropdowns(app, wb, csv, result)
    names = list(INPUT_NAMES)
    total = 0
    try:
        for label, filters in SCENARIOS.items():
            for name in names:
                wb.Names(name).RefersToRange.Value = filters.get(name)
            app.Calculate()
            want = expected_rows(csv, filters)
            shown_rows = _spill_rows(ws)
            result.filter_counts[label] = (shown_rows, len(want))
            if shown_rows != len(want):
                result.failures.append(
                    f"Player Database [{label}]: {shown_rows} rows, CSV {len(want)}"
                )
                continue
            total += _compare(label, _displayed(ws, shown_rows), want, result)
            if shown_rows == 0 and ws.Cells(FIRST_ROW, 1).Value2 != "":
                result.failures.append(f"Player Database [{label}]: empty result not blank")
            if error_cells(ws):
                result.failures.append(f"Player Database [{label}]: error values {error_cells(ws)}")
    finally:
        for name in names:
            wb.Names(name).RefersToRange.ClearContents()
        app.Calculate()
    result.values_compared["Player Database"] = total
