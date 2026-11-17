"""The README sheet: the workbook's front page, and the home of the `in_horizon` picker."""

from __future__ import annotations

from typing import Any

import wb_style as st

CREDIT_URL = "https://github.com/olbauday/FPL-Core-Insights"
SHEET_NAME = "README"
HORIZON_NAME = "in_horizon"
PROBLEM_NAME = "horizon_problem"  # empty, or a sentence saying what is wrong with in_horizon
MAX_HORIZON_NAME = "meta_max_horizon"  # derived name: the picker's upper limit, from tbl_meta
DEFAULT_HORIZON = 5
HORIZON_CELL = "C5"  # fixed so the name exists before the sheets that use it are built
XL_LEFT, XL_CENTRE, XL_TOP = -4131, -4108, -4160

# What each sheet does. The README lists a sheet only if it exists in the workbook.
SHEET_BLURBS: dict[str, str] = {
    SHEET_NAME: "This page: how to refresh, the horizon picker, data status and credits.",
    "Player Database": (
        "One row per player: price, status and news, ownership, minutes, points, per-90 "
        "numbers, penalty taker and this week's transfer and price moves. Filter with the "
        "yellow cells: a name search, team, position, status and a maximum price. Leave a "
        "cell empty to show everything."
    ),
    "Fixture Analysis": (
        "The next fixtures for all 20 clubs over the horizon, each cell showing the opponent "
        "and H or A, coloured by difficulty. The View cell switches between Attack and Defence. "
        "Clubs are sorted by their total over the horizon, best first."
    ),
}

HOW_TO_REFRESH = [
    (
        "On open",
        "The workbook refreshes its data every time you open it. Let it finish (see the "
        "status bar) before reading numbers.",
    ),
    ("Manually", "Data tab, then Refresh All. Do it if the workbook has been open for hours."),
    (
        "How fresh",
        "The model publishes twice a day, around 08:00 and 18:00 UTC, when the upstream FPL data "
        "has changed. GitHub can start a scheduled run late, sometimes by hours. It also caches "
        "each file for up to 5 minutes, so a refresh just after a publish can still show the "
        "previous run. Check Last updated above.",
    ),
    (
        "Offline",
        "If Excel can't reach GitHub it shows an error and keeps the data from the last "
        "successful refresh.",
    ),
]
FIRST_OPEN = [
    (
        "1. Protected View",
        "A copy downloaded from the internet or an email opens in Protected View (a yellow "
        "bar). Click Enable Editing. Nothing refreshes until you do.",
    ),
    (
        "2. External data warning",
        "A Security Warning bar says external data connections are disabled. Click Enable Content.",
    ),
    (
        "3. Anonymous access",
        "Excel asks how to connect to raw.githubusercontent.com. Choose Anonymous and click "
        "Connect. No sign-in is needed, because the data is public. Excel remembers the choice "
        "on that computer.",
    ),
]
SAFETY = (
    "Work in this workbook, not in the raw CSV files. The CSVs carry free text from the "
    "upstream data (player news and names), and Excel can run a cell that starts with =, +, - "
    "or @ as a formula when you open a CSV directly. This workbook loads the same data as "
    "plain values, which is safe."
)
GENERAL = (
    "Every number here comes from the model's published CSVs. The workbook displays them; it "
    "doesn't calculate expected points. Yellow cells with blue text are inputs. Everything "
    "else is locked against accidental edits (Review tab, Unprotect Sheet; there is no "
    "password)."
)
SCALE_KEY = (
    "xP and fixture difficulty use one colour scale on every sheet. Blue is good for you "
    "(high xP, an easy fixture) and orange is bad:"
)


class _Writer:
    """Writes README rows downward in columns B (label) and C (text) and tracks the row."""

    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self.row = 1

    def title(self, text: str) -> None:
        """Write the sheet title."""
        cell = self.ws.Cells(self.row, 2)
        cell.Value = text
        cell.Font.Size = 18
        cell.Font.Bold = True
        self.row += 1

    def section(self, text: str) -> None:
        """Write a section header row."""
        self.row += 1
        self.ws.Cells(self.row, 2).Value = text
        st.style_header(self.ws.Range(self.ws.Cells(self.row, 2), self.ws.Cells(self.row, 3)))
        self.row += 1

    def line(self, label: str, text: str) -> int:
        """Write one row and return its number."""
        if label:
            self.ws.Cells(self.row, 2).Value = label
            self.ws.Cells(self.row, 2).Font.Bold = True
        if text:
            self.ws.Cells(self.row, 3).Value = text
        self.row += 1
        return self.row - 1

    def formula(self, label: str, formula: str, number_format: str) -> None:
        """Write a label and a formula-driven value with a number format."""
        r = self.line(label, "")
        cell = self.ws.Cells(r, 3)
        cell.Formula2 = formula
        cell.NumberFormat = number_format
        cell.HorizontalAlignment = XL_LEFT


def define_names(wb: Any) -> None:
    """Define `in_horizon`, its upper limit and `horizon_problem`. Call once, after tbl_meta.

    `horizon_problem` is empty when the horizon is fine, and otherwise a sentence saying what is
    wrong (a cleared cell, text, a decimal, or a value outside 1 to the maximum). Typing is
    validated, but clearing or pasting can bypass that, so sheets show this message.
    """
    cell = f"${HORIZON_CELL[0]}${HORIZON_CELL[1:]}"
    h, top = HORIZON_NAME, MAX_HORIZON_NAME
    wb.Names.Add(h, f"={SHEET_NAME}!{cell}")
    wb.Names.Add(top, "=INDEX(tbl_meta[max_horizon],1)")
    rule = f'"The horizon must be a whole number from 1 to "&{top}&". "'
    bad = f"OR({h}<1,{h}>{top},{h}<>INT({h}))"
    wb.Names.Add(
        PROBLEM_NAME,
        f'=IF({h}="","The horizon is empty. "&{rule},'
        f'IF(NOT(ISNUMBER({h})),{rule},IF({bad},{rule},"")))',
    )


def _horizon_block(wb: Any, w: _Writer) -> None:
    """The picker. `define_names` must already have run."""
    w.section("Settings")
    r = w.line("Horizon (gameweeks)", "")
    cell = w.ws.Cells(r, 3)
    cell.Value = DEFAULT_HORIZON
    cell.HorizontalAlignment = XL_LEFT
    st.style_input(cell)
    if cell.GetAddress(False, False) != HORIZON_CELL:
        raise ValueError(f"the horizon input moved from {HORIZON_CELL}; update HORIZON_CELL")
    v = cell.Validation
    v.Delete()
    v.Add(
        st.XL_VALIDATE_WHOLE_NUMBER,
        st.XL_VALID_ALERT_STOP,
        st.XL_BETWEEN,
        "1",
        f"={MAX_HORIZON_NAME}",
    )
    v.InputTitle = "Horizon"
    v.InputMessage = "Gameweeks ahead, from 1 up to the model's maximum. Every sheet uses it."
    v.ErrorTitle = "Horizon"
    v.ErrorMessage = "Enter a whole number from 1 up to the model's maximum horizon."
    note = w.line("", "")
    w.ws.Cells(note, 3).Formula2 = (
        '="How many gameweeks ahead every sheet looks. It applies to the whole workbook. "'
        f"&{PROBLEM_NAME}"
    )


def _status_block(w: _Writer) -> None:
    """Data status: last updated, current gameweek, next deadline, model version."""
    w.section("Data status")
    w.formula("Last updated", "=INDEX(tbl_meta[run_utc],1)", st.DATETIME_FMT)
    w.formula("Current gameweek", "=INDEX(tbl_meta[current_gw],1)", "0")
    w.formula("Next deadline", "=INDEX(tbl_meta[next_deadline_utc],1)", st.DATETIME_FMT)
    w.formula("Model version", "=INDEX(tbl_meta[model_version],1)", "@")


def _sheets_block(wb: Any, w: _Writer) -> None:
    """List each sheet that exists, with a link, and what it does."""
    w.section("What each sheet does")
    present = {s.Name for s in wb.Worksheets if s.Visible == -1}
    for name, blurb in SHEET_BLURBS.items():
        if name not in present:
            continue
        r = w.line("", blurb)
        cell = w.ws.Cells(r, 2)
        if name == SHEET_NAME:
            cell.Value = name  # no link to this page from itself
        else:
            w.ws.Hyperlinks.Add(cell, "", f"'{name}'!A1", f"Go to {name}", name)
        cell.Font.Bold = True


def _colour_key(w: _Writer) -> None:
    """The input colour and the shared scale, shown as swatches."""
    w.section("Colour key")
    r = w.line("Inputs", "Yellow fill with blue text: cells you can change.")
    st.style_input(w.ws.Cells(r, 2))
    w.ws.Cells(r, 2).Locked = True
    w.line("Scale", SCALE_KEY)
    for hex_colour, label in (
        (st.SCALE_LOW, "Worse"),
        (st.SCALE_MID, "Middle"),
        (st.SCALE_HIGH, "Better"),
    ):
        cell = w.ws.Cells(w.line("", ""), 2)
        cell.Value = label
        cell.Interior.Color = st.rgb(hex_colour)
        cell.HorizontalAlignment = XL_CENTRE


def _credit_block(w: _Writer) -> None:
    """The data credit and its link."""
    w.section("Data credit")
    w.line(
        "Source",
        "Match and player data come from FPL-Core-Insights by olbauday. The model's own "
        "calculations are built on it.",
    )
    r = w.line("", CREDIT_URL)
    w.ws.Hyperlinks.Add(Anchor=w.ws.Cells(r, 3), Address=CREDIT_URL, TextToDisplay=CREDIT_URL)


def _layout(app: Any, ws: Any) -> None:
    """Column widths, wrapping, print setup, frozen header and protection."""
    ws.Columns(1).ColumnWidth = 2
    ws.Columns(2).ColumnWidth = 26
    ws.Columns(3).ColumnWidth = 100
    ws.Range("B:C").VerticalAlignment = XL_TOP
    ws.Columns(3).WrapText = True
    ws.Rows.AutoFit()
    ws.Activate()
    app.ActiveWindow.DisplayGridlines = False
    ws.PageSetup.Orientation = 2
    ws.PageSetup.Zoom = False
    ws.PageSetup.FitToPagesWide = 1
    ws.PageSetup.FitToPagesTall = False
    st.freeze_header(app, ws, rows=2)
    st.protect_sheet(ws)


def build_readme(app: Any, wb: Any, ws: Any) -> None:
    """Fill the README sheet. Run it after the data tables and every other sheet exist."""
    w = _Writer(ws)
    w.title("FPL expected points model")
    w.line("", "Read this page first.")
    _horizon_block(wb, w)
    _status_block(w)
    w.section("How to refresh")
    for label, text in HOW_TO_REFRESH:
        w.line(label, text)
    w.section("The first time you open it")
    for label, text in FIRST_OPEN:
        w.line(label, text)
    _sheets_block(wb, w)
    w.section("Use the workbook, not the raw CSVs")
    w.line("", SAFETY)
    w.line("", GENERAL)
    _colour_key(w)
    _credit_block(w)
    _layout(app, ws)
