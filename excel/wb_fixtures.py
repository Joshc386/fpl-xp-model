"""The Fixture Analysis sheet: 20 clubs by the gameweeks in the horizon, from tbl_fixtures.

The visible grid only displays. A hidden, protected `Data_Grid` sheet does the lookups:
- the club list is `UNIQUE(tbl_players[team])`, which always has all 20 clubs (tbl_fixtures
  would drop a club with no fixture in the horizon). `team` is the same short name in both
  tables (contract note, 2026-11-14);
- each club and gameweek holds the sum of that gameweek's rows (the contract's rule for a
  double gameweek), and "-" when there is no row (a blank gameweek);
- clubs are sorted by their horizon total, highest first, in both views. High is good for the
  manager in both: more goals expected for the club (Attack, `lambda_for`) or a higher
  clean-sheet chance (Defence, `p_cs`).
Colour: an Excel colour scale can't colour a text cell by a number elsewhere, so each cell is
coloured by a stepped rule from a number on `Data_Grid`, using the shared palette. That number
is the cell's per-match average: a double shows the sum in its text but is coloured by the mean
of its two matches. Why: a summed double is nearly twice a single and would become the top of
the range, pushing every single fixture towards orange. By average, the same colour means the
same difficulty of one match in every cell. The Total column uses the same lowest-to-highest
scale (`wb_style.apply_scale`).
"""

from __future__ import annotations

from typing import Any

import wb_style as st

SHEET_NAME = "Fixture Analysis"
GRID_SHEET = f"{st.DATA_PREFIX}Grid"
VIEW_NAME = "in_fixture_view"
VIEWS = ("Attack", "Defence")  # a blank view shows Attack
GRID_GWS = 5  # grid columns; the horizon picker's maximum must not exceed it
TEAMS = 20  # Premier League clubs: rows in the grid
DASH = "–"  # shown for a blank gameweek
HEADER_ROW = 5
FIRST_ROW = HEADER_ROW + 1
LAST_ROW = HEADER_ROW + TEAMS
TOTAL_COL, GW_COL = 2, 3  # visible columns: Club, Total, then one column per gameweek
LAST_COL = GW_COL + GRID_GWS - 1

# Data_Grid columns (1-based): alphabetical clubs, numbers, text, totals, sort order, sorted copies.
C_TEAM, C_NUM, C_TXT, C_TOT, C_ORD = 1, 3, 9, 15, 16
C_STEAM, C_STXT, C_STOT, C_SBIN, C_BIN = 18, 19, 24, 26, 32
C_AVG = 38  # per-match average of each cell, which sets its colour
C_MIN = 44  # cells holding the lowest and highest average (rows 1 and 2)

NAMES = {"meta_next_gw": "=INDEX(tbl_meta[next_gw],1)"}


def letter(col: int) -> str:
    """Excel column letters for a 1-based index."""
    out = ""
    while col:
        col, rem = divmod(col - 1, 26)
        out = chr(65 + rem) + out
    return out


def _rows(k: int) -> str:
    """The criteria shared by every lookup of club $A{r} in the k-th gameweek of the horizon."""
    return "tbl_fixtures[team],$A{r},tbl_fixtures[gw],meta_next_gw+" + f"{k}-1"


def number_formula(k: int, r: int) -> str:
    """Club's value in gameweek k: sum of its rows; empty if none or beyond the horizon."""
    crit = _rows(k).format(r=r)
    return (
        f'=IF(OR($A{r}="",{k}>in_horizon),"",IF(COUNTIFS({crit})=0,"",'
        f'IF({VIEW_NAME}="Defence",SUMIFS(tbl_fixtures[p_cs],{crit}),'
        f"SUMIFS(tbl_fixtures[lambda_for],{crit}))))"
    )


def text_formula(k: int, r: int) -> str:
    """Opponents with H or A, a dash for a blank gameweek, and the sum for a double."""
    crit = _rows(k).format(r=r)
    num = f"{letter(C_NUM + k - 1)}{r}"
    opponents = (
        'TEXTJOIN(" + ",TRUE,FILTER(tbl_fixtures[opponent]&" ("&IF(tbl_fixtures[home],"H","A")&")",'
        f"(tbl_fixtures[team]=$A{r})*(tbl_fixtures[gw]=meta_next_gw+{k}-1)))"
    )
    return (
        f'=IF(OR($A{r}="",{k}>in_horizon),"",IF(COUNTIFS({crit})=0,"{DASH}",'
        f'{opponents}&IF(COUNTIFS({crit})>1," = "&FIXED({num},2,TRUE),"")))'
    )


def header_formula(k: int) -> str:
    """Header of the k-th gameweek column: `GW {next_gw + k - 1}`, empty past the horizon."""
    return f'=IF({k}>in_horizon,"","GW "&(meta_next_gw+{k}-1))'


def average_formula(k: int, r: int) -> str:
    """The cell's value per match: its sum divided by its number of fixtures (1 or 2)."""
    crit = _rows(k).format(r=r)
    num = f"{letter(C_NUM + k - 1)}{r}"
    return f'=IF({num}="","",{num}/COUNTIFS({crit}))'


def bin_formula(k: int, r: int) -> str:
    """Step 0..SCALE_STEPS of the cell's per-match average between the grid's lowest and highest."""
    num = f"{letter(C_AVG + k - 1)}{r}"
    lo, hi = f"${letter(C_MIN)}$1", f"${letter(C_MIN)}$2"
    return (
        f'=IF({num}="","",IF({hi}={lo},{st.SCALE_STEPS // 2},'
        f"ROUND({st.SCALE_STEPS}*({num}-{lo})/({hi}-{lo}),0)))"
    )


def _fill_grid_sheet(ws: Any) -> None:
    """Write every Data_Grid formula: clubs, values, text, averages, bins, totals, order."""
    last = LAST_ROW - HEADER_ROW + 1  # row 21 on Data_Grid
    ws.Cells(2, C_TEAM).Formula2 = "=SORT(UNIQUE(tbl_players[team]))"
    averages = f"{letter(C_AVG)}2:{letter(C_AVG + GRID_GWS - 1)}{last}"
    ws.Cells(1, C_MIN).Formula2 = f"=MIN({averages})"
    ws.Cells(2, C_MIN).Formula2 = f"=MAX({averages})"
    for r in range(2, last + 1):
        for k in range(1, GRID_GWS + 1):
            ws.Cells(r, C_NUM + k - 1).Formula2 = number_formula(k, r)
            ws.Cells(r, C_TXT + k - 1).Formula2 = text_formula(k, r)
            ws.Cells(r, C_AVG + k - 1).Formula2 = average_formula(k, r)
            ws.Cells(r, C_BIN + k - 1).Formula2 = bin_formula(k, r)
        first, end = letter(C_NUM), letter(C_NUM + GRID_GWS - 1)
        ws.Cells(r, C_TOT).Formula2 = f'=IF($A{r}="",-1,SUM({first}{r}:{end}{r}))'
    tot = f"{letter(C_TOT)}2:{letter(C_TOT)}{last}"
    ws.Cells(2, C_ORD).Formula2 = f"=SORTBY(SEQUENCE(ROWS({tot})),{tot},-1)"
    order = f"${letter(C_ORD)}$2#"
    team = f"$A$2:$A${last}"
    ws.Cells(2, C_STEAM).Formula2 = f"=INDEX({team},{order})"
    for k in range(GRID_GWS):
        for src, dst in ((C_TXT, C_STXT), (C_BIN, C_SBIN)):
            col = letter(src + k)
            ws.Cells(2, dst + k).Formula2 = f"=INDEX({col}$2:{col}${last},{order})"
    total = f"${letter(C_TOT)}$2:${letter(C_TOT)}${last}"
    ws.Cells(2, C_STOT).Formula2 = f'=IF(INDEX({team},{order})="","",INDEX({total},{order}))'


def _build_grid_sheet(wb: Any) -> None:
    """Create the hidden, protected Data_Grid sheet."""
    ws = wb.Worksheets.Add(None, wb.Worksheets(wb.Worksheets.Count))
    ws.Name = GRID_SHEET
    _fill_grid_sheet(ws)
    st.protect_sheet(ws)
    ws.Visible = st.XL_SHEET_HIDDEN


def _build_view_input(ws: Any, wb: Any) -> None:
    """The Attack or Defence dropdown, named `in_fixture_view`."""
    ws.Cells(3, 3).Value = "View"
    ws.Cells(3, 3).Font.Bold = True
    cell = ws.Cells(4, 3)
    cell.Value = VIEWS[0]
    st.style_input(cell)
    wb.Names.Add(VIEW_NAME, f"='{SHEET_NAME}'!{cell.GetAddress(True, True)}")
    v = cell.Validation
    v.Delete()
    v.Add(st.XL_VALIDATE_LIST, st.XL_VALID_ALERT_STOP, st.XL_BETWEEN, ",".join(VIEWS))
    v.InputTitle = "View"
    v.InputMessage = "Attack: goals the club is expected to score. Defence: clean-sheet chance."
    v.ErrorMessage = "Pick Attack or Defence."
    v.IgnoreBlank = False


def _build_header(ws: Any) -> None:
    """Title, note, horizon link and value, guard message and the column headers."""
    ws.Cells(1, 1).Value = SHEET_NAME
    ws.Cells(1, 1).Font.Size = 18
    ws.Cells(1, 1).Font.Bold = True
    ws.Cells(2, 1).Formula2 = (
        f'=IF({VIEW_NAME}="Defence","Defence: blue is a higher clean-sheet chance (p_cs). ",'
        '"Attack: blue is more goals expected for the club (lambda_for). ")'
        '&"Clubs are sorted by the total over the horizon, highest first. "'
        '&"A dash is a blank gameweek; a double shows both opponents and their combined value."'
    )
    ws.Cells(2, 1).Font.Color = st.rgb(st.NOTE_FONT)
    ws.Hyperlinks.Add(
        ws.Cells(3, 1), "", "README!C5", "Change the horizon on the README sheet", "Horizon"
    )
    ws.Cells(3, 1).Font.Bold = True
    ws.Cells(4, 1).Formula2 = "=in_horizon"
    ws.Cells(4, 1).NumberFormat = '0" GW"'
    ws.Cells(4, 1).HorizontalAlignment = -4131
    ws.Cells(4, 5).Formula2 = (
        f'=horizon_problem&IF(meta_max_horizon>{GRID_GWS},"The grid holds {GRID_GWS} gameweeks '
        f'but the model now projects more: rebuild the workbook. ","")'
        f'&IF(ROWS(UNIQUE(tbl_players[team]))>{TEAMS},"tbl_players has more than {TEAMS} clubs: '
        f'the grid shows the first {TEAMS}, A-Z. ","")'
    )
    ws.Cells(4, 5).Font.Bold = True
    ws.Cells(HEADER_ROW, 1).Value = "Club"
    ws.Cells(HEADER_ROW, TOTAL_COL).Value = "Total"
    for k in range(1, GRID_GWS + 1):
        ws.Cells(HEADER_ROW, GW_COL + k - 1).Formula2 = header_formula(k)
    header = ws.Range(ws.Cells(HEADER_ROW, 1), ws.Cells(HEADER_ROW, LAST_COL))
    st.style_header(header)
    header.HorizontalAlignment = -4108


def _fill_visible(ws: Any) -> None:
    """The visible grid: spills from Data_Grid, the total colour scale and widths."""
    grid = f"{GRID_SHEET}!"
    ws.Cells(FIRST_ROW, 1).Formula2 = f"={grid}${letter(C_STEAM)}$2#"
    for k in range(GRID_GWS):
        ws.Cells(FIRST_ROW, GW_COL + k).Formula2 = f"={grid}${letter(C_STXT + k)}$2#"
    total = ws.Cells(FIRST_ROW, TOTAL_COL)
    total.Formula2 = f"={grid}${letter(C_STOT)}$2#"
    column = ws.Range(total, ws.Cells(LAST_ROW, TOTAL_COL))
    column.NumberFormat = "0.00"
    column.Font.Bold = True
    st.apply_scale(column)
    body = ws.Range(ws.Cells(FIRST_ROW, GW_COL), ws.Cells(LAST_ROW, LAST_COL))
    body.HorizontalAlignment = -4108
    ws.Range(ws.Cells(FIRST_ROW, 1), ws.Cells(LAST_ROW, 1)).Font.Bold = True
    ws.Columns(1).ColumnWidth = 10
    ws.Range(ws.Columns(GW_COL), ws.Columns(LAST_COL)).ColumnWidth = 26
    ws.Columns(TOTAL_COL).ColumnWidth = 10


def _colour_rules(ws: Any) -> None:
    """Dash cells grey, other cells a step of the shared scale from the number in Data_Grid."""
    body = ws.Range(ws.Cells(FIRST_ROW, GW_COL), ws.Cells(LAST_ROW, LAST_COL))
    ws.Activate()
    ws.Cells(FIRST_ROW, GW_COL).Select()  # relative references in the rules are taken from here
    dash = body.FormatConditions.Add(st.XL_CELL_VALUE, st.XL_EQUAL, f'="{DASH}"')
    dash.Interior.Color = st.rgb(st.GREY_DASH)
    anchor = f"{GRID_SHEET}!{letter(C_SBIN)}2"
    for step in range(st.SCALE_STEPS + 1):
        rule = body.FormatConditions.Add(2, 0, f"={anchor}={step}")  # xlExpression
        rule.Interior.Color = st.rgb(st.scale_colour(step))


def build_fixture_analysis(app: Any, wb: Any) -> Any:
    """Create the Fixture Analysis sheet and its hidden Data_Grid. Needs tbl_fixtures, tbl_meta."""
    ws = st.new_sheet(wb, SHEET_NAME)
    for name, formula in NAMES.items():
        wb.Names.Add(name, formula)
    _build_view_input(ws, wb)
    _build_grid_sheet(wb)
    _build_header(ws)
    _fill_visible(ws)
    _colour_rules(ws)
    app.ActiveWindow.DisplayGridlines = False
    st.freeze_header(app, ws, rows=HEADER_ROW, cols=1)
    ws.PageSetup.Orientation = 2
    ws.PageSetup.Zoom = False
    ws.PageSetup.FitToPagesWide = 1
    ws.PageSetup.FitToPagesTall = False
    st.protect_sheet(ws)
    return ws
