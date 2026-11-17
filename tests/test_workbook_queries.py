"""Workbook foundation, no Excel needed: queries against the contract, base path, README, scan.

The .pq files are checked against docs/data_contract.md and the published CSVs, because a
mistyped column in M would load silently wrong.
"""

from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from workbook_helpers import ROOT, contract_columns  # puts excel/ on sys.path

# isort: split

import build_workbook
import check_workbook
import wb_data
import wb_readme
import wb_style

LOADED = {
    "players": "players.csv",
    "fixture_difficulty": "fixture_difficulty.csv",
    "meta": "meta.csv",
}
# One pattern for both {"col", Int64.Type} and {"col", each ..., type datetime} entries.
_TYPE_ENTRY = re.compile(r'\{"(\w+)",\s*(?:each [^\n]*?,\s*)?(Int64\.Type|type \w+)\}')
_PANDAS_KIND = {"Int64.Type": "i", "type number": "f", "type logical": "b"}


def query_types(query: str) -> dict[str, str]:
    """Column -> M type for a query, taking the last type each column is given."""
    text = (wb_data.QUERY_DIR / f"{query}.pq").read_text(encoding="utf-8")
    return dict(_TYPE_ENTRY.findall(text))


@pytest.mark.parametrize(("query", "file"), LOADED.items())
def test_query_columns_match_contract(query: str, file: str) -> None:
    assert list(query_types(query)) == contract_columns(file)


@pytest.mark.parametrize(("query", "file"), LOADED.items())
def test_query_types_match_published_csv(query: str, file: str) -> None:
    csv = pd.read_csv(ROOT / "outputs" / file)
    assert list(csv.columns) == list(query_types(query))
    for column, m_type in query_types(query).items():
        kind = csv[column].dtype.kind
        if m_type in _PANDAS_KIND:
            assert kind == _PANDAS_KIND[m_type], column
        else:  # text, and the two UTC timestamps, which are ISO text in the CSV
            assert kind in "OTUS" or str(csv[column].dtype) == "str", column
    assert query_types("meta")["run_utc"] == "type datetime"
    assert query_types("meta")["next_deadline_utc"] == "type datetime"


def test_every_loaded_query_uses_the_one_base_path() -> None:
    texts = wb_data.read_queries()
    assert set(texts) == set(wb_data.QUERIES)
    assert "BasePath & file" in texts["GetCsv"]
    for query, file in LOADED.items():
        assert f'GetCsv("{file}")' in texts[query]
        assert "http" not in texts[query]  # no query hardcodes a source
    assert "IsParameterQuery = true" in texts["BasePath"]


def test_base_path_is_swapped_and_release_is_the_default() -> None:
    assert wb_data.RELEASE_BASE in wb_data.read_queries()["BasePath"]
    local = wb_data.read_queries("C:\\data\\out\\")["BasePath"]
    assert "C:\\data\\out\\" in local
    assert wb_data.RELEASE_BASE not in local
    with pytest.raises(ValueError):
        wb_data.read_queries('bad"path')


def test_base_path_is_normalised() -> None:
    no_slash = wb_data.RELEASE_BASE.rstrip("/")
    assert wb_data.normalise_base_path(no_slash) == wb_data.RELEASE_BASE
    assert wb_data.normalise_base_path(wb_data.RELEASE_BASE) == wb_data.RELEASE_BASE
    relative = wb_data.normalise_base_path("excel/sample_outputs")
    assert Path(relative).is_absolute() and relative.endswith(os.sep)
    assert Path(relative) == (Path.cwd() / "excel" / "sample_outputs").resolve()


def test_refresh_on_open_settings() -> None:
    assert wb_data.REFRESH_ON_OPEN is True and wb_data.BACKGROUND_REFRESH is False


def test_tables_follow_the_naming_convention() -> None:
    assert [t for _, t in wb_data.TABLES.values()] == ["tbl_players", "tbl_fixtures", "tbl_meta"]
    assert all(sheet.startswith(wb_style.DATA_PREFIX) for sheet, _ in wb_data.TABLES.values())
    assert wb_readme.HORIZON_NAME == "in_horizon"


def test_standards_constants() -> None:
    assert wb_style.PRICE_FMT == '£0.0"m"'
    assert wb_style.PCT_FMT == "0%"
    assert wb_style.rgb("#FF0000") == 255  # Excel colours are BGR
    assert wb_style.rgb("#0000FF") == 255 * 65536
    assert len({wb_style.SCALE_LOW, wb_style.SCALE_MID, wb_style.SCALE_HIGH}) == 3


@pytest.mark.parametrize(
    ("cell", "csv_text", "column", "expected"),
    [
        (None, "", "news", True),
        (None, "x", "news", False),
        (1.504, "1.5", "ppg", True),
        (1.52, "1.5", "ppg", False),
        (True, "True", "home", True),
        (True, "False", "home", False),
        ("Raya", "Raya", "web_name", True),
        (46342.5, "2026-11-16T15:57:50Z", "run_utc", False),
        (46342.66516203704, "2026-11-16T15:57:50Z", "run_utc", True),
    ],
)
def test_reconciliation_comparison(
    cell: object, csv_text: str, column: str, expected: bool
) -> None:
    assert check_workbook._same(cell, csv_text, column) is expected


def test_importing_the_builder_needs_no_windows_modules() -> None:
    # pywin32 is imported inside functions only, so Linux CI can import every module.
    source = (ROOT / "excel" / "build_workbook.py").read_text(encoding="utf-8")
    head = source.split("def start_excel", 1)[0]
    assert "win32" not in head
    assert build_workbook.FINAL_PATH.name == "FPL_Model.xlsx"


def test_readme_says_runs_can_be_late_without_fixed_times() -> None:
    text = " ".join(t for _, t in wb_readme.HOW_TO_REFRESH)
    assert "around 08:00 and 18:00 UTC" in text and "late" in text


def _zip_with(tmp_path: Path, parts: dict[str, bytes]) -> Path:
    path = tmp_path / "x.xlsx"
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in parts.items():
            zf.writestr(name, data)
    return path


def test_personal_info_scan_finds_names_paths_and_emails(tmp_path: Path) -> None:
    release = wb_data.RELEASE_BASE
    public = release + " " + wb_data.REPO_URL + "blob/main/x"
    path = _zip_with(
        tmp_path,
        {
            "docProps/core.xml": b"<dc:creator>Josh Cohen</dc:creator>",
            "xl/workbook.xml": rb'<x absPath="C:\Users\someone\excel\build\"/>',
            "xl/other.xml": b"mail me at a.b@example.com",
            "xl/public.xml": public.encode(),
        },
    )
    hits = check_workbook.personal_info_hits(path, release)
    assert any("core.xml" in h and "Josh" in h for h in hits)
    assert any("core.xml" in h and "Cohen" in h for h in hits)
    assert any("workbook.xml" in h and "Users" in h for h in hits)
    assert any("email" in h and "example.com" in h for h in hits)
    # the public URLs hold the owner's login on purpose, so they are not hits
    assert not any("public.xml" in h for h in hits)


def test_the_committed_workbook_holds_no_personal_details() -> None:
    final = build_workbook.FINAL_PATH
    if not final.exists():
        pytest.skip("excel/FPL_Model.xlsx is not built yet")
    assert check_workbook.personal_info_hits(final, wb_data.RELEASE_BASE) == []
