"""The synthetic redirect's guard: no `fpl` or `backtest` module can bypass the swap."""

from __future__ import annotations

import importlib
import pkgutil
import sys
import types
from pathlib import Path

import backtest
import pytest

import fpl
from elo_check_synth import CALLERS, stray_callers, synth_point
from fpl.features import load_as_of


def import_everything() -> list[str]:
    """Import every module of the `fpl` and `backtest` packages; return their names."""
    names = []
    for pkg in (fpl, backtest):
        for info in pkgutil.walk_packages(pkg.__path__, prefix=f"{pkg.__name__}."):
            importlib.import_module(info.name)
            names.append(info.name)
    return names


def test_every_module_holding_load_as_of_is_swapped() -> None:
    names = import_everything()
    assert "backtest.elo_check" in names and "fpl.models.elo" in names
    assert stray_callers() == []
    holders = {n for n in names if getattr(sys.modules[n], "load_as_of", None) is load_as_of}
    assert holders - {"fpl.features"} == {m.__name__ for m in CALLERS}


def test_a_new_caller_stops_the_synthetic_redirect(monkeypatch: pytest.MonkeyPatch,
                                                   tmp_path: Path) -> None:
    planted = types.ModuleType("backtest.planted_caller")
    planted.load_as_of = load_as_of
    monkeypatch.setitem(sys.modules, planted.__name__, planted)
    elsewhere = types.ModuleType("planted_outside")  # not fpl or backtest: not the guard's
    elsewhere.load_as_of = load_as_of
    monkeypatch.setitem(sys.modules, elsewhere.__name__, elsewhere)
    assert stray_callers() == ["backtest.planted_caller"]
    with pytest.raises(RuntimeError, match="backtest.planted_caller"), synth_point(tmp_path):
        pass


def test_the_swap_reaches_every_caller_and_is_undone(tmp_path: Path) -> None:
    with synth_point(tmp_path / "data"):
        assert all(m.load_as_of is not load_as_of for m in CALLERS)
        assert stray_callers() == []
    assert all(m.load_as_of is load_as_of for m in CALLERS)
