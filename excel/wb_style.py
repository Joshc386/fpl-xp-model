"""Workbook-wide standards shared by every sheet builder (brief section 10).

Colours, number formats, the input style, frozen headers, sheet protection and the one
colour scale live here, so a sheet builder never picks its own. Importing this module needs no
Excel: every function takes the COM objects it works on.
"""

from __future__ import annotations

from typing import Any

# --- Colours (hex, converted to Excel's BGR integers by `rgb`) -------------------------------
INPUT_FILL = "#FFF2CC"  # the one fill for every input cell
INPUT_FONT = "#0000FF"  # blue text on inputs: the usual modelling convention
HEADER_FILL = "#1F3864"
HEADER_FONT = "#FFFFFF"
NOTE_FONT = "#595959"
LINK_FONT = "#0563C1"

# The colour-blind-safe scale for xP and difficulty, identical on every sheet. It runs
# orange - near-white - blue (ColorBrewer's PuOr family, which stays distinct under red-green
# and blue-yellow colour blindness, and in greyscale by lightness). Blue is always the end that
# is good for the manager: high xP, an easy fixture, a likely clean sheet. Orange is the bad end.
SCALE_LOW = "#F1A340"
SCALE_MID = "#F7F7F7"
SCALE_HIGH = "#67A9CF"
SCALE_STEPS = 10  # stepped version of the scale, for cells whose colour follows another cell
GREY_DASH = "#D9D9D9"  # blank gameweek cells
# FPL availability status fills, from the same palette. The status letter stays in the cell, so
# colour is never the only signal.
STATUS_FILL = {
    "a": SCALE_HIGH,  # available: blue
    "d": "#F8D1A0",  # doubtful: pale orange
    "i": SCALE_LOW,  # injured: orange
    "s": SCALE_LOW,  # suspended: orange
    "u": "#BFBFBF",  # unavailable: grey
}

# --- Number formats (Excel's US-English format codes) ----------------------------------------
PRICE_FMT = '£0.0"m"'
XP_FMT = "0.0"
PCT_FMT = "0%"
PCT_POINTS_FMT = '0.0"%"'  # for columns already in percentage points (selected_pct 47.6)
PRICE_CHANGE_FMT = '+£0.0"m";-£0.0"m";£0.0"m"'
COUNT_FMT = "#,##0"
SIGNED_COUNT_FMT = "+#,##0;-#,##0;0"
PER90_FMT = "0.00"
DATETIME_FMT = 'yyyy-mm-dd hh:mm "UTC"'

# --- Excel constants -------------------------------------------------------------------------
XL_VALUE_LOWEST, XL_VALUE_HIGHEST, XL_VALUE_FORMULA = 1, 2, 4
XL_VALIDATE_WHOLE_NUMBER, XL_VALID_ALERT_STOP, XL_BETWEEN = 1, 1, 1
XL_SHEET_HIDDEN = 0
XL_CELL_VALUE, XL_EQUAL, XL_VALIDATE_LIST, XL_VALIDATE_DECIMAL, XL_GREATER_EQUAL = 1, 3, 3, 2, 7

DATA_PREFIX = "Data_"  # hidden data sheets


def rgb(hex_colour: str) -> int:
    """Convert '#RRGGBB' to the integer Excel's Color properties expect (BGR order)."""
    h = hex_colour.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r + g * 256 + b * 65536


def scale_colour(step: int) -> str:
    """Hex colour of step 0..SCALE_STEPS on the shared scale (0 orange, middle white, top blue).

    Used where a text cell must take its colour from a number in another cell, which Excel's
    colour-scale rule can't do. The endpoints and midpoint are the same three colours.
    """
    t = step / SCALE_STEPS
    lo, mid, hi = (SCALE_LOW, SCALE_MID, SCALE_HIGH)
    a, b, u = (lo, mid, t * 2) if t <= 0.5 else (mid, hi, (t - 0.5) * 2)
    channels = [
        round(int(a[i : i + 2], 16) + (int(b[i : i + 2], 16) - int(a[i : i + 2], 16)) * u)
        for i in (1, 3, 5)
    ]
    return "#{:02X}{:02X}{:02X}".format(*channels)


def new_sheet(wb: Any, name: str) -> Any:
    """Add a visible sheet before the first hidden Data_ sheet, or last if there is none."""
    first_data = next(
        (s for s in wb.Worksheets if s.Name.startswith(DATA_PREFIX)),
        None,
    )
    if first_data is not None:
        ws = wb.Worksheets.Add(first_data)
    else:
        ws = wb.Worksheets.Add(None, wb.Worksheets(wb.Worksheets.Count))
    ws.Name = name
    return ws


def style_input(cell: Any) -> None:
    """Give an input cell the shared fill and font, and unlock it so protection allows edits."""
    cell.Interior.Color = rgb(INPUT_FILL)
    cell.Font.Color = rgb(INPUT_FONT)
    cell.Locked = False


def style_header(rng: Any) -> None:
    """Style a header row: white bold text on the dark fill."""
    rng.Interior.Color = rgb(HEADER_FILL)
    rng.Font.Color = rgb(HEADER_FONT)
    rng.Font.Bold = True


def apply_scale(rng: Any) -> None:
    """Apply the shared 3-colour scale to a range: lowest value orange, highest blue.

    The middle colour sits at the arithmetic middle of the range's lowest and highest value
    (not the median), so the colour of a value depends only on where it falls between them.
    That is the same rule as the stepped `scale_colour`, so the same colour means the same thing.
    """
    address = rng.GetAddress(True, True)
    cs = rng.FormatConditions.AddColorScale(3)
    kinds = (XL_VALUE_LOWEST, XL_VALUE_FORMULA, XL_VALUE_HIGHEST)
    for i, (kind, colour) in enumerate(
        zip(kinds, (SCALE_LOW, SCALE_MID, SCALE_HIGH), strict=True), 1
    ):
        crit = cs.ColorScaleCriteria(i)
        crit.Type = kind
        if kind == XL_VALUE_FORMULA:
            crit.Value = f"=(MIN({address})+MAX({address}))/2"
        crit.FormatColor.Color = rgb(colour)


def freeze_header(app: Any, ws: Any, rows: int, cols: int = 0) -> None:
    """Freeze the top `rows` rows (and left `cols` columns) of a sheet."""
    ws.Activate()
    window = app.ActiveWindow
    window.FreezePanes = False
    window.ScrollRow = window.ScrollColumn = 1
    window.SplitRow = rows
    window.SplitColumn = cols
    window.FreezePanes = True


def protect_sheet(ws: Any) -> None:
    """Protect a user sheet with no password. Input cells are unlocked by `style_input`.

    Filtering, sorting and column resizing stay allowed. Never used on the Data_ sheets: a
    protected sheet blocks the table resizing a refresh needs.
    """
    ws.Protect(
        DrawingObjects=True,
        Contents=True,
        Scenarios=True,
        AllowFormattingColumns=True,
        AllowFiltering=True,
        AllowSorting=True,
    )
