"""Shared helpers for the workbook tests (test_workbook_*.py): paths, the contract, the Excel gate.

The expectations written out here are deliberately independent of the builder's own constants,
so a wrong label, number format or dropdown in the builder fails a test.
"""

from __future__ import annotations

import faulthandler
import importlib.util
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "excel" / "sample_outputs"
sys.path.insert(0, str(ROOT / "excel"))

# Player Database columns, in the brief's order: (header, players.csv column, number format).
PLAYER_COLUMNS = (
    ("Player", "web_name", "General"),
    ("Team", "team", "General"),
    ("Position", "position", "General"),
    ("Price", "price_m", '£0.0"m"'),
    ("Status", "status", "General"),
    ("News", "news", "General"),
    ("Chance of playing", "chance_next", '0.0"%"'),
    ("Ownership", "selected_pct", '0.0"%"'),
    ("Minutes", "minutes", "#,##0"),
    ("Starts", "starts", "#,##0"),
    ("Total points", "total_points", "#,##0"),
    ("Points per game", "ppg", "0.0"),
    ("xG per 90", "xg90", "0.00"),
    ("xA per 90", "xa90", "0.00"),
    ("Defensive contributions per 90", "dc90", "0.00"),
    ("Penalty taker", "pen_taker", "General"),
    ("Net transfers this GW", "net_transfers_gw", "+#,##0;-#,##0;0"),
    ("Price change this GW", "price_change_gw", '+£0.0"m";-£0.0"m";£0.0"m"'),
    ("Price change since start", "price_change_start", '+£0.0"m";-£0.0"m";£0.0"m"'),
)


def contract_columns(file: str) -> list[str]:
    """The column list for one published CSV, from the contract's Published outputs table."""
    text = (ROOT / "docs" / "data_contract.md").read_text(encoding="utf-8")
    section = text.split("## Published outputs", 1)[1].split("## Conventions", 1)[0]
    row = next(line for line in section.splitlines() if line.startswith(f"| `{file}`"))
    return re.findall(r"`(\w+)`", row.split("|")[3])


def csv_rows(file: str) -> int:
    """Data rows in a published CSV in outputs/ (what a local build loads)."""
    return len(pd.read_csv(ROOT / "outputs" / file))


def _excel_available() -> bool:
    if sys.platform != "win32" or importlib.util.find_spec("win32com") is None:
        return False
    import winreg

    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Excel.Application"))
    except OSError:
        return False
    return True


needs_excel = pytest.mark.skipif(not _excel_available(), reason="needs Windows Excel (COM)")


@contextmanager
def faulthandler_muted() -> Iterator[None]:
    """Mute pytest's faulthandler while Excel quits.

    Releasing COM references to a quit Excel raises a handled RPC_E_DISCONNECTED that
    faulthandler prints as a "fatal exception" dump. It is harmless.
    """
    was_enabled = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        yield
    finally:
        if was_enabled:
            faulthandler.enable()
