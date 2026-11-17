"""Checks run on a built workbook: refresh, error values, row counts and reconciliation.

`check` works on an open workbook, so the build can run it before replacing the real file.
It reads the CSVs from the same base path the workbook's queries use.
"""

from __future__ import annotations

import base64
import codecs
import io
import re
import struct
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from wb_data import QUERIES, RELEASE_BASE, REPO_URL, TABLES

TOLERANCE = 0.01
UTC_TOLERANCE_DAYS = 1 / 86400  # one second, in Excel date serial units
EXCEL_EPOCH = datetime(1899, 12, 30)
XL_CELL_FORMULAS, XL_CELL_CONSTANTS, XL_ERRORS = -4123, 2, 16
NO_CELLS_FOUND = -2146827284  # SpecialCells' error when nothing matches
# Personal details that must not reach the public repo. The path terms apply to a release build
# only: a development build holds its local base path on purpose.
NAME_TERMS = ("Josh", "Cohen")
PATH_TERMS = ("joshc", "C:\\Users", "C:/Users")
EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+")


@dataclass
class CheckResult:
    """Failures found, plus what was compared (for the report)."""

    failures: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=dict)
    values_compared: dict[str, int] = field(default_factory=dict)
    grid_stats: dict[str, tuple[int, int]] = field(default_factory=dict)  # label -> (blank, double)
    filter_counts: dict[str, tuple[int, int]] = field(default_factory=dict)  # label -> (Excel, CSV)

    @property
    def ok(self) -> bool:
        """True when no check failed."""
        return not self.failures


def read_csv(base_path: str, file: str) -> pd.DataFrame:
    """Read a published CSV as text, so nothing is guessed or coerced."""
    return pd.read_csv(base_path + file, dtype=str, keep_default_na=False)


def error_cells(ws: Any) -> list[str]:
    """Addresses of cells showing an Excel error value (#N/A, #REF!, ...) on a sheet."""
    from pywintypes import com_error  # Windows only; imported here so Linux can import this module

    found: list[str] = []
    for kind in (XL_CELL_FORMULAS, XL_CELL_CONSTANTS):
        try:
            found.append(ws.UsedRange.SpecialCells(kind, XL_ERRORS).Address)
        except com_error as exc:
            if exc.excepinfo[5] != NO_CELLS_FOUND:  # anything but "no cells found" is real
                raise
    return found


def _same(cell: Any, csv_text: str, column: str) -> bool:
    """True if an Excel cell value equals the CSV text (numbers to 0.01, times to a second)."""
    if cell is None:
        return csv_text == ""
    if isinstance(cell, bool):
        return csv_text == str(cell)
    if isinstance(cell, float | int):
        if column.endswith("_utc"):
            stamp = pd.Timestamp(csv_text).tz_localize(None).to_pydatetime()
            return abs(cell - (stamp - EXCEL_EPOCH).total_seconds() / 86400) <= UTC_TOLERANCE_DAYS
        return csv_text != "" and abs(cell - float(csv_text)) <= TOLERANCE
    return str(cell) == csv_text


def _reconcile_table(lo: Any, csv: pd.DataFrame, result: CheckResult) -> None:
    """Compare a loaded table's headers, row count and every value with its CSV."""
    name = lo.Name
    headers = [str(h) for h in lo.HeaderRowRange.Value2[0]]
    if headers != list(csv.columns):
        result.failures.append(f"{name}: columns {headers} differ from the CSV {list(csv.columns)}")
        return
    rows = lo.DataBodyRange.Value2
    if len(rows) != len(csv):
        result.failures.append(f"{name}: {len(rows)} rows, CSV has {len(csv)}")
        return
    bad = compared = 0
    for r, csv_row in enumerate(csv.itertuples(index=False)):
        for c, column in enumerate(headers):
            compared += 1
            if not _same(rows[r][c], csv_row[c], column):
                bad += 1
                if bad <= 5:
                    result.failures.append(
                        f"{name} row {r + 1} {column}: Excel {rows[r][c]!r}, CSV {csv_row[c]!r}"
                    )
    result.values_compared[name] = compared
    if bad > 5:
        result.failures.append(f"{name}: {bad} mismatched values in all")


def _check_refresh_on_open(wb: Any, result: CheckResult) -> None:
    """Every table's connection must refresh on open, in the foreground."""
    for query, (sheet_name, table_name) in TABLES.items():
        lo = wb.Worksheets(sheet_name).ListObjects(table_name)
        conn = lo.QueryTable.WorkbookConnection.OLEDBConnection
        if not conn.RefreshOnFileOpen:
            result.failures.append(f"{table_name} ({query}): refresh on open is off")
        if conn.BackgroundQuery:
            result.failures.append(f"{table_name} ({query}): background refresh is on")
    if wb.Connections.Count != len(TABLES):
        result.failures.append(f"{wb.Connections.Count} connections for {len(TABLES)} tables")


def _mashup_parts(data: bytes) -> list[tuple[str, bytes]]:
    """The query package inside customXml (base64, then a zip), plus the bytes after it."""
    text = data.decode(
        "utf-16" if data[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE) else "utf-8"
    )
    match = re.search(r">([A-Za-z0-9+/=]+)</DataMashup>", text)
    if match is None:
        return []
    raw = base64.b64decode(match.group(1))
    (length,) = struct.unpack("<I", raw[4:8])
    with zipfile.ZipFile(io.BytesIO(raw[8 : 8 + length])) as package:
        parts = [(f"DataMashup/{n}", package.read(n)) for n in package.namelist()]
    return [*parts, ("DataMashup/metadata", raw[8 + length :])]


def personal_info_hits(path: Path, base_path: str) -> list[str]:
    """Search every part of a saved .xlsx, and the queries packed inside it, for personal details.

    It looks for names, user paths and email addresses. The public repository URLs are removed
    first: they hold the owner's login on purpose. So is the base path of a development build
    (a local folder), which is the only place a user path may appear, and only in the queries.
    """
    release = base_path == RELEASE_BASE
    terms = NAME_TERMS + (PATH_TERMS if release else ())
    hits: list[str] = []
    with zipfile.ZipFile(path) as zf:
        parts = [(i.filename, zf.read(i.filename)) for i in zf.infolist()]
    for name in [n for n, _ in parts if n.startswith("customXml/item")]:
        parts += _mashup_parts(dict(parts)[name])
    for name, data in parts:
        for public in (RELEASE_BASE, REPO_URL, base_path):
            data = data.replace(public.encode(), b"")
        hits += [f"{name}: {t!r}" for t in terms if t.lower().encode() in data.lower()]
        hits += [f"{name}: email {m.decode()!r}" for m in EMAIL.findall(data)]
    return hits


def check(app: Any, wb: Any, base_path: str) -> CheckResult:
    """Refresh every query, then check refresh-on-open, errors, row counts and every value."""
    result = CheckResult()
    _check_refresh_on_open(wb, result)
    wb.RefreshAll()
    app.CalculateUntilAsyncQueriesDone()
    app.Calculate()
    for query, (sheet_name, table_name) in TABLES.items():
        lo = wb.Worksheets(sheet_name).ListObjects(table_name)
        csv = read_csv(base_path, QUERIES[query])
        result.row_counts[table_name] = lo.ListRows.Count
        _reconcile_table(lo, csv, result)
    for ws in wb.Worksheets:
        cells = error_cells(ws)
        if cells:
            result.failures.append(f"{ws.Name}: error values at {cells}")
    horizon = wb.Names("in_horizon").RefersToRange.Value2
    max_horizon = app.Evaluate("meta_max_horizon+0")
    if not (isinstance(horizon, float) and 1 <= horizon <= max_horizon):
        result.failures.append(f"in_horizon is {horizon!r}, outside 1 to {max_horizon!r}")
    return result
