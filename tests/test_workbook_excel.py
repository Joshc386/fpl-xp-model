"""Real builds through Excel (COM). Skipped, cleanly, where Windows Excel isn't installed.

One build from the local outputs/ folder, and one from excel/sample_outputs/ (a blank and a
double gameweek in the horizon). Each build runs every check in `check_*`; these tests read the
workbook-wide standards back from the saved file.
"""

from __future__ import annotations

import pytest

from workbook_helpers import (
    PLAYER_COLUMNS,
    ROOT,
    SAMPLE,
    csv_rows,
    faulthandler_muted,
    needs_excel,
)

# isort: split

import build_workbook
import check_fixtures
import check_players
import wb_data
import wb_readme
import wb_style

pytestmark = needs_excel
INPUT_FILL = wb_style.rgb(wb_style.INPUT_FILL)
PLAYER_INPUTS = ("in_search", "in_team", "in_position", "in_max_price", "in_status")


def _frozen(app: object) -> tuple:
    window = app.ActiveWindow
    return (window.FreezePanes, window.SplitRow, window.SplitColumn)


def _read_player_db(app: object, wb: object) -> dict:
    ws = wb.Worksheets("Player Database")
    cells = {n: wb.Names(n).RefersToRange for n in PLAYER_INPUTS}
    ws.Activate()
    last = len(PLAYER_COLUMNS) + 1
    return {
        "inputs": {n: (c.Locked, c.Interior.Color) for n, c in cells.items()},
        "protected": ws.ProtectContents,
        "frozen": _frozen(app),
        "formats": [ws.Cells(7, i).NumberFormat for i in range(1, last)],
        "headers": [ws.Cells(6, i).Value for i in range(1, last)],
        "status_rules": ws.Cells(7, 5).FormatConditions.Count,
        "lists_hidden": wb.Worksheets("Data_Lists").Visible,
    }


def _read_fixtures(app: object, wb: object) -> dict:
    ws = wb.Worksheets("Fixture Analysis")
    view = wb.Names("in_fixture_view").RefersToRange
    ws.Activate()
    return {
        "protected": ws.ProtectContents,
        "view": (view.Value2, view.Locked, view.Interior.Color, view.Validation.Formula1),
        "frozen": _frozen(app),
        "grid_hidden": wb.Worksheets("Data_Grid").Visible,
        "grid_protected": wb.Worksheets("Data_Grid").ProtectContents,
        "clubs": [ws.Cells(r, 1).Value2 for r in range(6, 26)],
        "rules": ws.Cells(6, 3).FormatConditions.Count,
    }


def _read_workbook(app: object, wb: object) -> dict:
    readme = wb.Worksheets("README")
    horizon = wb.Names("in_horizon").RefersToRange
    facts = {
        "sheets": {s.Name: (s.Visible, s.ProtectContents) for s in wb.Worksheets},
        "tables": {lo.Name: lo.ListRows.Count for s in wb.Worksheets for lo in s.ListObjects},
        "queries": [q.Name for q in wb.Queries],
        "refresh_on_open": [c.OLEDBConnection.RefreshOnFileOpen for c in wb.Connections],
        "horizon": (horizon.Value2, horizon.Locked, horizon.Interior.Color),
        "validation": (horizon.Validation.Type, horizon.Validation.Formula2),
        "locked_other": readme.Range("C9").Locked,
        "date_format": readme.Range("C9").NumberFormat,
        "text": " ".join(str(c.Value) for c in readme.UsedRange.Cells if c.Value),
        "credit_link": [h.Address for h in readme.Hyperlinks],
        "order": [wb.Worksheets(i).Name for i in range(1, wb.Worksheets.Count + 1)],
    }
    readme.Activate()
    facts["frozen"] = _frozen(app)
    facts["player_db"] = _read_player_db(app, wb)
    facts["fixtures"] = _read_fixtures(app, wb)
    return facts


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Build from the local outputs/ folder, then read the standards back from the saved file."""
    path = tmp_path_factory.mktemp("wb") / "FPL_Model.new.xlsx"
    with faulthandler_muted():
        result = build_workbook.build(path, str(ROOT / "outputs") + "\\")
        with build_workbook.ExcelSession() as xl:
            wb = xl.app.Workbooks.Open(str(path))
            try:
                facts = _read_workbook(xl.app, wb)
                wb.Close(SaveChanges=False)
            finally:
                wb = None
    return {"result": result, **facts}


@pytest.fixture(scope="module")
def built_sample(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Build from excel/sample_outputs/, which has a blank and a double gameweek in the horizon."""
    path = tmp_path_factory.mktemp("wbs") / "FPL_Model.sample.xlsx"
    with faulthandler_muted():
        return {"result": build_workbook.build(path, str(SAMPLE) + "\\")}


def test_build_refreshes_and_reconciles(built: dict) -> None:
    result = built["result"]
    assert result.ok, result.failures  # includes refresh on open and the personal-info scan
    want = {
        "tbl_players": csv_rows("players.csv"),
        "tbl_fixtures": csv_rows("fixture_difficulty.csv"),
        "tbl_meta": csv_rows("meta.csv"),
    }
    assert built["tables"] == want
    assert result.row_counts == want
    assert sum(result.values_compared.values()) > 20


def test_build_applies_the_standards(built: dict) -> None:
    sheets = built["sheets"]
    assert sheets["README"] == (-1, True)  # visible, protected
    assert all(sheets[n][0] == 0 for n in sheets if n.startswith("Data_"))  # hidden
    assert built["queries"] == list(wb_data.QUERIES)
    assert built["refresh_on_open"] == [True, True, True]
    value, locked, fill = built["horizon"]
    assert (value, locked, fill) == (5.0, False, INPUT_FILL)
    assert built["validation"][0] == wb_style.XL_VALIDATE_WHOLE_NUMBER
    assert "meta_max_horizon" in built["validation"][1]
    assert built["locked_other"] is True
    assert built["frozen"] == (True, 2.0, 0.0)
    assert "UTC" in built["date_format"]


def test_readme_content(built: dict) -> None:
    for needle in (
        "Protected View",
        "Enable Content",
        "Anonymous",
        "Refresh All",
        "not in the raw",
    ):
        assert needle in built["text"]
    assert wb_readme.CREDIT_URL in built["credit_link"]


def test_player_database_filters_match_the_csv(built: dict) -> None:
    result = built["result"]
    assert result.ok, result.failures
    counts = result.filter_counts
    assert set(counts) == set(check_players.SCENARIOS)
    assert all(shown == want for shown, want in counts.values())
    assert counts["no filters"] == (csv_rows("players.csv"),) * 2
    assert counts["team ARS + search 'zzzz' (no match)"] == (0, 0)
    assert result.values_compared["Player Database"] > 20


def test_player_database_standards(built: dict) -> None:
    pdb = built["player_db"]
    assert built["order"][:2] == ["README", "Player Database"]  # user sheets lead
    assert pdb["protected"] is True
    assert set(pdb["inputs"]) == set(PLAYER_INPUTS)
    assert all(not locked and colour == INPUT_FILL for locked, colour in pdb["inputs"].values())
    assert pdb["frozen"] == (True, 6.0, 1.0)
    assert pdb["formats"] == [fmt for _, _, fmt in PLAYER_COLUMNS]
    assert pdb["headers"] == [header for header, _, _ in PLAYER_COLUMNS]
    assert pdb["status_rules"] == len(wb_style.STATUS_FILL)
    assert pdb["lists_hidden"] == wb_style.XL_SHEET_HIDDEN


def test_fixture_analysis_reconciles_in_both_views_and_every_horizon(built: dict) -> None:
    result = built["result"]
    assert result.ok, result.failures
    expected = {f"{v}, horizon {h}" for v in check_fixtures.VIEW_COLUMN for h in (1, 3, 5)}
    assert set(result.grid_stats) == expected
    assert result.values_compared["Fixture Analysis"] >= 20 * 2 * 3


def test_fixture_analysis_standards(built: dict) -> None:
    fx = built["fixtures"]
    assert built["order"][:3] == ["README", "Player Database", "Fixture Analysis"]
    assert fx["protected"] is True and fx["grid_protected"] is True
    assert fx["grid_hidden"] == wb_style.XL_SHEET_HIDDEN
    assert fx["view"] == ("Attack", False, INPUT_FILL, "Attack,Defence")
    assert fx["frozen"] == (True, 5.0, 1.0)
    assert len(fx["clubs"]) == 20 and all(fx["clubs"])  # every club has a row
    assert fx["rules"] == 1 + wb_style.SCALE_STEPS + 1  # a dash rule, then one rule per step


def test_fixture_analysis_blank_and_double_gameweeks(built_sample: dict) -> None:
    result = built_sample["result"]
    assert result.ok, result.failures
    assert result.grid_stats["Attack, horizon 5"] == (2, 2)  # a blank and a double for two clubs
    assert result.grid_stats["Defence, horizon 5"] == (2, 2)
    assert result.grid_stats["Attack, horizon 1"] == (0, 0)  # neither falls in GW11 alone
