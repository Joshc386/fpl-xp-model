"""Build the FPL workbook through Excel's object model (Windows, Excel 365 installed).

    python excel/build_workbook.py [--base-path DIR_OR_URL] [--no-replace]

The build starts its own hidden Excel (never one the user has open), writes a new file in
excel/build/, refreshes and checks it, then replaces excel/FPL_Model.xlsx. The default base path
is the raw GitHub URL of outputs/ on main; `--base-path` points it at a local folder (relative
or absolute) for development. A workbook built with a local path is never moved over
FPL_Model.xlsx.
"""

from __future__ import annotations

import argparse
import gc
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import wb_data
import wb_fixtures
import wb_players
import wb_readme
from check_fixtures import check_fixture_analysis
from check_players import check_player_database
from check_workbook import CheckResult, check, personal_info_hits

log = logging.getLogger("build_workbook")

EXCEL_DIR = Path(__file__).resolve().parent
BUILD_DIR = EXCEL_DIR / "build"
FINAL_PATH = EXCEL_DIR / "FPL_Model.xlsx"
XLSX_FORMAT = 51
QUIT_WAIT_SECONDS = 15
PERSONAL_PROPERTIES = ("Author", "Last Author", "Company", "Manager")


def start_excel() -> tuple[Any, Any, int]:
    """Start a new, hidden Excel of our own; return it with a process handle and its pid.

    DispatchEx always creates a new process; Dispatch could attach to the user's own Excel. The
    handle is opened at once and kept for the session: while it is open, Windows can't reuse
    the pid for another process, so stopping through it can never hit someone else's Excel.
    """
    import win32api
    import win32com.client
    import win32con
    import win32process

    app = win32com.client.DispatchEx("Excel.Application")
    app.Visible = False
    app.DisplayAlerts = False
    app.AskToUpdateLinks = False
    _, pid = win32process.GetWindowThreadProcessId(app.Hwnd)
    access = win32con.PROCESS_TERMINATE | win32con.SYNCHRONIZE
    handle = win32api.OpenProcess(access, False, pid)
    log.info("Started Excel %s (pid %s)", app.Version, pid)
    return app, handle, pid


class ExcelSession:
    """Our own Excel instance for the length of a `with` block, always quit on the way out.

    Excel only exits once every COM reference to it is released, so `__exit__` drops ours before
    waiting on the process handle. If Excel is still running after the wait, it is terminated
    through that same handle, then the handle is closed.
    """

    def __enter__(self) -> ExcelSession:
        self.app, self._handle, self.pid = start_excel()
        return self

    def __exit__(self, *exc_info: object) -> None:
        import win32api
        import win32event
        import win32process

        try:
            self.app.Quit()
        except Exception:
            log.exception("Excel.Quit failed; will stop our process %s if it stays", self.pid)
        self.app = None
        gc.collect()
        waited = win32event.WaitForSingleObject(self._handle, QUIT_WAIT_SECONDS * 1000)
        if waited != win32event.WAIT_OBJECT_0:
            log.warning("Excel pid %s did not quit; terminating that process only", self.pid)
            win32process.TerminateProcess(self._handle, 1)
        win32api.CloseHandle(self._handle)


def build_sheets(app: Any, wb: Any, base_path: str) -> None:
    """Create every sheet, in order: README shell, queries and tables, names, user sheets.

    A new user sheet adds its builder after `define_names` and before the README fill, and
    uses `wb_style.new_sheet` so user sheets stay to the left of the Data_ sheets.
    """
    readme = wb.Worksheets(1)
    readme.Name = wb_readme.SHEET_NAME
    wb_data.add_queries(wb, wb_data.read_queries(base_path))
    for query in wb_data.TABLES:
        wb_data.load_table(wb, query)
    wb_readme.define_names(wb)  # once: every later sheet uses these names
    wb_players.build_player_database(app, wb)
    wb_fixtures.build_fixture_analysis(app, wb)
    wb_readme.build_readme(app, wb, readme)
    readme.Activate()
    readme.Range(wb_readme.HORIZON_CELL).Select()


def strip_personal_info(wb: Any) -> None:
    """Remove the author, last-modified-by and company from the file before it is saved."""
    wb.RemovePersonalInformation = True
    for name in PERSONAL_PROPERTIES:
        wb.BuiltinDocumentProperties(name).Value = ""


def build(out_path: Path, base_path: str) -> CheckResult:
    """Build the workbook to `out_path`, refresh and check it, save it and scan the file."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with ExcelSession() as xl:
        wb = xl.app.Workbooks.Add()
        try:
            build_sheets(xl.app, wb, base_path)
            result = check(xl.app, wb, base_path)
            check_player_database(xl.app, wb, base_path, result)
            check_fixture_analysis(xl.app, wb, base_path, result)
            strip_personal_info(wb)
            wb.SaveAs(str(out_path), FileFormat=XLSX_FORMAT)
            wb.Close(SaveChanges=False)
        finally:
            wb = None  # release our reference so Excel can exit
    result.failures.extend(personal_info_hits(out_path, base_path))
    return result


def _is_locked(path: Path) -> bool:
    """True if `path` exists but can't be opened for writing (Excel has it open)."""
    if not path.exists():
        return False
    try:
        with path.open("ab"):
            return False
    except PermissionError:
        return True


def _log_result(result: CheckResult) -> None:
    """Log what the checks compared."""
    for table, rows in result.row_counts.items():
        values = result.values_compared.get(table)
        log.info("%s: %s rows, %s values reconciled", table, rows, values)
    for sheet in ("Player Database", "Fixture Analysis"):
        log.info("%s: %s values reconciled", sheet, result.values_compared.get(sheet))
    for label, (blank, double) in result.grid_stats.items():
        log.info("Fixture Analysis [%s]: %s blank cells, %s doubles", label, blank, double)
    for label, (shown, want) in result.filter_counts.items():
        log.info("Player Database [%s]: %s rows (CSV %s)", label, shown, want)


def main(argv: list[str] | None = None) -> int:
    """Command line entry: build, check, and (for a release build) replace FPL_Model.xlsx."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base-path", default=wb_data.RELEASE_BASE, help="folder (relative ok) or https URL"
    )
    parser.add_argument("--no-replace", action="store_true", help="leave the build in excel/build/")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    base = wb_data.normalise_base_path(args.base_path)
    replace = base == wb_data.RELEASE_BASE and not args.no_replace
    if replace and _is_locked(FINAL_PATH):
        log.error("%s is open in Excel. Close it and run the build again.", FINAL_PATH)
        return 1
    # A unique name per build: a stray open copy of an earlier build can't block this one.
    new_path = BUILD_DIR / f"FPL_Model.{time.strftime('%Y%m%d-%H%M%S')}.xlsx"
    result = build(new_path, base)
    _log_result(result)
    if not result.ok:
        for failure in result.failures:
            log.error("CHECK FAILED: %s", failure)
        return 1
    if not replace:
        log.info("Built %s (not replacing FPL_Model.xlsx)", new_path)
        return 0
    try:
        os.replace(new_path, FINAL_PATH)
    except PermissionError:
        log.error("%s is open in Excel. The checked build is at %s", FINAL_PATH, new_path)
        return 1
    log.info("Replaced %s", FINAL_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
