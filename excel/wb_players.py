"""The Player Database sheet: one row per player from tbl_players, filtered by five inputs.

Design: dropdown and text inputs feed one filter, and every column is a spill formula over the
same row list (`pd_rows`). Slicers can't work here. A slicer acts on an Excel Table, and the
only table holding these rows is tbl_players on a hidden sheet that a refresh resizes (so it
can't be protected or shown). A FILTER spill can't carry a slicer. Dropdowns keep team,
position, status, a price cap and a name search working together, with no manual steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import wb_style as st
from wb_data import REPO_URL

SHEET_NAME = "Player Database"
LISTS_SHEET = f"{st.DATA_PREFIX}Lists"
CONTEXT_URL = REPO_URL + "blob/main/CONTEXT.md"
HEADER_ROW = 6
FIRST_ROW = HEADER_ROW + 1
LAST_FORMAT_ROW = 2000  # formats and status colours are set well past the 672 players
CONTROLS_ROW = 4


@dataclass(frozen=True)
class Column:
    """One displayed column: its tbl_players column, header, number format, width and kind.

    kind: plain, text_blank (blank text shows empty), num_blank (a blank number shows empty,
    not 0) or bool (True shows Yes, False shows empty).
    """

    source: str
    header: str
    fmt: str
    width: float
    kind: str = "plain"


# The brief's column order, limited to what players.csv holds (player_id is the key, not shown).
COLUMNS: tuple[Column, ...] = (
    Column("web_name", "Player", "General", 18),
    Column("team", "Team", "General", 7),
    Column("position", "Position", "General", 9),
    Column("price_m", "Price", st.PRICE_FMT, 9),
    Column("status", "Status", "General", 8),
    Column("news", "News", "General", 42, "text_blank"),
    Column("chance_next", "Chance of playing", st.PCT_POINTS_FMT, 10, "num_blank"),
    Column("selected_pct", "Ownership", st.PCT_POINTS_FMT, 10),
    Column("minutes", "Minutes", st.COUNT_FMT, 9),
    Column("starts", "Starts", st.COUNT_FMT, 8),
    Column("total_points", "Total points", st.COUNT_FMT, 9),
    Column("ppg", "Points per game", "0.0", 9),
    Column("xg90", "xG per 90", st.PER90_FMT, 9),
    Column("xa90", "xA per 90", st.PER90_FMT, 9),
    Column("dc90", "Defensive contributions per 90", st.PER90_FMT, 14),
    Column("pen_taker", "Penalty taker", "General", 9, "bool"),
    Column("net_transfers_gw", "Net transfers this GW", st.SIGNED_COUNT_FMT, 11),
    Column("price_change_gw", "Price change this GW", st.PRICE_CHANGE_FMT, 11),
    Column("price_change_start", "Price change since start", st.PRICE_CHANGE_FMT, 11),
)

# Control: (label, input name, column index it sits above). Search sits over the name column.
INPUTS = (
    ("Search name", "in_search", 0),
    ("Team", "in_team", 1),
    ("Position", "in_position", 2),
    ("Max price", "in_max_price", 3),
    ("Status", "in_status", 4),
)
# Dropdown lists live on a hidden sheet: name -> (cell, spill formula).
LISTS = {
    "in_team": ("A1", "=SORT(UNIQUE(tbl_players[team]))"),
    "in_position": ("B1", "=UNIQUE(tbl_players[position])"),
    "in_status": ("C1", "=SORT(UNIQUE(tbl_players[status]))"),
}

_T = "tbl_players"
KEEP = (
    f'=((in_team="")+({_T}[team]=in_team)>0)'
    f'*((in_position="")+({_T}[position]=in_position)>0)'
    f'*((in_status="")+({_T}[status]=in_status)>0)'
    f'*((in_max_price="")+({_T}[price_m]<=in_max_price)>0)'
    f'*((in_search="")+ISNUMBER(FIND(LOWER(in_search),LOWER({_T}[web_name])))>0)'
)
SEQ = f"SEQUENCE(ROWS({_T}[player_id]))"
NAMES = {
    "pd_keep": KEEP,
    "pd_count": "=SUM(--pd_keep)",
    # Matching row positions in tbl_players, highest total points first (ties keep CSV order).
    "pd_rows": f"=SORTBY(FILTER({SEQ},pd_keep,0),FILTER({_T}[total_points],pd_keep,0),-1)",
}


def column_formula(col: Column) -> str:
    """The spill formula for one column. With no matches it shows empty, never an error."""
    cell = f"INDEX({_T}[{col.source}],pd_rows)"
    if col.kind == "text_blank":
        body = f'{cell}&""'
    elif col.kind == "num_blank":
        body = f'IF({cell}&""="","",{cell})'
    elif col.kind == "bool":
        body = f'IF({cell},"Yes","")'
    else:
        body = cell
    return f'=IF(pd_count=0,"",{body})'


def _build_lists(wb: Any) -> None:
    """Hidden sheet holding the dropdown lists, one spill per input."""
    ws = wb.Worksheets.Add(None, wb.Worksheets(wb.Worksheets.Count))
    ws.Name = LISTS_SHEET
    for name, (cell, formula) in LISTS.items():
        ws.Range(cell).Formula2 = formula
        wb.Names.Add(f"lst_{name[3:]}", f"={LISTS_SHEET}!${cell[0]}$1#")
    st.protect_sheet(ws)
    ws.Visible = st.XL_SHEET_HIDDEN


def _style_input(ws: Any, wb: Any, label: str, name: str, col: int) -> None:
    """One filter input: label, input style, its name and its validation."""
    ws.Cells(CONTROLS_ROW - 1, col + 1).Value = label
    ws.Cells(CONTROLS_ROW - 1, col + 1).Font.Bold = True
    cell = ws.Cells(CONTROLS_ROW, col + 1)
    st.style_input(cell)
    wb.Names.Add(name, f"='{SHEET_NAME}'!{cell.GetAddress(True, True)}")
    if name == "in_search":
        return  # free text: no validation
    v = cell.Validation
    v.Delete()
    if name == "in_max_price":
        v.Add(st.XL_VALIDATE_DECIMAL, st.XL_VALID_ALERT_STOP, st.XL_GREATER_EQUAL, "0")
        v.InputMessage = "Show players at or below this price in £m. Clear to show all."
        v.ErrorMessage = "Enter a price in £m, or clear the cell."
        cell.NumberFormat = st.PRICE_FMT
    else:
        v.Add(st.XL_VALIDATE_LIST, st.XL_VALID_ALERT_STOP, st.XL_BETWEEN, f"=lst_{name[3:]}")
        v.InputMessage = "Pick one, or clear the cell (Delete) to show all."
        v.ErrorMessage = "Pick a value from the list, or clear the cell."
    v.InputTitle = label


def _build_headers(ws: Any) -> None:
    """Header row, widths, number formats and the first formula of every column."""
    for i, col in enumerate(COLUMNS, 1):
        ws.Cells(HEADER_ROW, i).Value = col.header
        ws.Columns(i).ColumnWidth = col.width
        body = ws.Range(ws.Cells(FIRST_ROW, i), ws.Cells(LAST_FORMAT_ROW, i))
        body.NumberFormat = col.fmt
        if col.kind == "bool":
            body.HorizontalAlignment = -4108
        ws.Cells(FIRST_ROW, i).Formula2 = column_formula(col)
    header = ws.Range(ws.Cells(HEADER_ROW, 1), ws.Cells(HEADER_ROW, len(COLUMNS)))
    st.style_header(header)
    header.WrapText = True
    header.VerticalAlignment = -4108
    ws.Rows(HEADER_ROW).RowHeight = 48


def _status_colours(ws: Any) -> None:
    """Fill the status column by FPL status, from the shared palette."""
    status = ws.Range(ws.Cells(FIRST_ROW, 5), ws.Cells(LAST_FORMAT_ROW, 5))
    for code, colour in st.STATUS_FILL.items():
        cond = status.FormatConditions.Add(st.XL_CELL_VALUE, st.XL_EQUAL, f'="{code}"')
        cond.Interior.Color = st.rgb(colour)
    status.HorizontalAlignment = -4108


def _notes(ws: Any) -> None:
    """Title, status key, the "Showing N of M" line and the link to the definitions."""
    ws.Cells(1, 1).Value = SHEET_NAME
    ws.Cells(1, 1).Font.Size = 18
    ws.Cells(1, 1).Font.Bold = True
    ws.Cells(2, 1).Value = (
        "Status: a available, d doubtful, i injured, s suspended, u unavailable. "
        "A blank chance of playing means FPL has set no flag. Sorted by total points."
    )
    ws.Cells(2, 1).Font.Color = st.rgb(st.NOTE_FONT)
    ws.Hyperlinks.Add(
        ws.Cells(5, 6), CONTEXT_URL, "", "Open CONTEXT.md", "Metric definitions: CONTEXT.md"
    )
    ws.Cells(5, 1).Formula2 = '="Showing "&pd_count&" of "&ROWS(tbl_players[player_id])&" players"'
    ws.Cells(5, 1).Font.Bold = True


def build_player_database(app: Any, wb: Any) -> Any:
    """Create the Player Database sheet. Needs tbl_players to exist."""
    ws = st.new_sheet(wb, SHEET_NAME)
    _build_lists(wb)
    for label, name, col in INPUTS:  # inputs and lists first: the named formulas use them
        _style_input(ws, wb, label, name, col)
    for name, formula in NAMES.items():
        wb.Names.Add(name, formula)
    _notes(ws)
    _build_headers(ws)
    _status_colours(ws)
    ws.Activate()
    app.ActiveWindow.DisplayGridlines = False
    st.freeze_header(app, ws, rows=HEADER_ROW, cols=1)
    ws.PageSetup.Orientation = 2
    ws.PageSetup.PrintTitleRows = f"${HEADER_ROW}:${HEADER_ROW}"
    ws.PageSetup.Zoom = False
    ws.PageSetup.FitToPagesWide = 1
    ws.PageSetup.FitToPagesTall = False
    st.protect_sheet(ws)
    return ws
