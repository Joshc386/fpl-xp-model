"""Power Query loading: the .pq files in queries/ become workbook queries and hidden tables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from wb_style import DATA_PREFIX, XL_SHEET_HIDDEN

QUERY_DIR = Path(__file__).parent / "queries"
REPO_URL = "https://github.com/Joshc386/fpl-xp-model/"
RELEASE_BASE = "https://raw.githubusercontent.com/Joshc386/fpl-xp-model/main/outputs/"

# Query name -> the published CSV it reads (None for the parameter and the helper function).
QUERIES: dict[str, str | None] = {
    "BasePath": None,
    "GetCsv": None,
    "players": "players.csv",
    "fixture_difficulty": "fixture_difficulty.csv",
    "meta": "meta.csv",
}
# Query name -> (hidden sheet, table name). One table per output CSV loaded in phase 1.
TABLES: dict[str, tuple[str, str]] = {
    "players": (f"{DATA_PREFIX}Players", "tbl_players"),
    "fixture_difficulty": (f"{DATA_PREFIX}Fixtures", "tbl_fixtures"),
    "meta": (f"{DATA_PREFIX}Meta", "tbl_meta"),
}
_OLEDB = (
    "OLEDB;Provider=Microsoft.Mashup.OleDb.1;Data Source=$Workbook$;"
    'Location={query};Extended Properties=""'
)
XL_SRC_EXTERNAL, XL_YES, XL_CMD_SQL = 0, 1, 2
REFRESH_ON_OPEN = True  # every table refreshes when the workbook opens...
BACKGROUND_REFRESH = False  # ...in the foreground, so numbers are final once it is done


def normalise_base_path(base: str) -> str:
    """A URL gets a trailing slash; a folder (relative or absolute) becomes absolute with a trailing
    separator. The release URL with or without its trailing slash gives `RELEASE_BASE`."""
    if base.startswith("https://"):
        return base if base.endswith("/") else base + "/"
    return str(Path(base).resolve()) + os.sep


def read_queries(base_path: str = RELEASE_BASE) -> dict[str, str]:
    """Return each query's M text, with `base_path` swapped in for the release URL."""
    if '"' in base_path:
        raise ValueError("base path must not contain a double quote")
    texts = {name: (QUERY_DIR / f"{name}.pq").read_text(encoding="utf-8") for name in QUERIES}
    if RELEASE_BASE not in texts["BasePath"]:
        raise ValueError("BasePath.pq no longer holds the release URL")
    texts["BasePath"] = texts["BasePath"].replace(RELEASE_BASE, base_path)
    return texts


def add_queries(wb: Any, texts: dict[str, str]) -> None:
    """Add every query to the workbook as a connection-only query."""
    for name, formula in texts.items():
        wb.Queries.Add(name, formula)


def load_table(wb: Any, query: str) -> Any:
    """Load a query to its hidden Data_ sheet as an Excel Table, refreshed on open.

    Returns the ListObject. The refresh runs in the foreground so the caller can read the rows.
    """
    sheet_name, table_name = TABLES[query]
    ws = wb.Worksheets.Add(None, wb.Worksheets(wb.Worksheets.Count))
    ws.Name = sheet_name
    connection = _OLEDB.format(query=query)
    lo = ws.ListObjects.Add(XL_SRC_EXTERNAL, connection, True, XL_YES, ws.Range("A1"))
    qt = lo.QueryTable
    qt.CommandType = XL_CMD_SQL
    qt.CommandText = f"SELECT * FROM [{query}]"
    qt.BackgroundQuery = False
    qt.AdjustColumnWidth = False
    qt.RefreshStyle = 1  # xlInsertDeleteCells: the table grows and shrinks with the CSV
    qt.Refresh(False)
    lo.Name = table_name
    lo.TableStyle = ""
    qt.WorkbookConnection.OLEDBConnection.RefreshOnFileOpen = REFRESH_ON_OPEN
    qt.WorkbookConnection.OLEDBConnection.BackgroundQuery = BACKGROUND_REFRESH
    ws.Visible = XL_SHEET_HIDDEN
    return lo
