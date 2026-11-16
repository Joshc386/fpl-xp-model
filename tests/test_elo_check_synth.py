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
import fpl.features
import fpl.models.elo
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
    holders = {n for n in names
               if any(v is load_as_of for v in vars(sys.modules[n]).values())}
    assert holders - {"fpl.features"} == {m.__name__ for m in CALLERS}


def plant(monkeypatch: pytest.MonkeyPatch, name: str, **attrs: object) -> None:
    module = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(module, k, v)
    monkeypatch.setitem(sys.modules, name, module)


@pytest.mark.parametrize("name", ["fpl.planted_caller", "backtest.planted_caller"])
def test_a_new_caller_stops_the_synthetic_redirect(monkeypatch: pytest.MonkeyPatch,
                                                   tmp_path: Path, name: str) -> None:
    """Both packages are guarded: dropping either from `PACKAGES` fails one case."""
    plant(monkeypatch, name, load_as_of=load_as_of)
    plant(monkeypatch, "planted_outside", load_as_of=load_as_of)  # not fpl or backtest
    assert stray_callers() == [name]
    with pytest.raises(RuntimeError, match=name), synth_point(tmp_path):
        pass


def test_an_aliased_import_is_a_stray_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    plant(monkeypatch, "backtest.planted_alias", read_tables=load_as_of)
    assert stray_callers() == ["backtest.planted_alias"]


def test_an_alias_inside_a_swapped_module_is_a_stray_caller(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the `load_as_of` name of a module in `CALLERS` is swapped."""
    monkeypatch.setattr(fpl.models.elo, "planted_loader", load_as_of, raising=False)
    assert stray_callers() == ["fpl.models.elo"]


def with_default(season: str, as_of: int, loader: object = load_as_of) -> object:
    return loader


def with_kw_default(season: str, *, loader: object = load_as_of) -> object:
    return loader


class Reader:
    def read(self, loader: object = load_as_of) -> object:
        return loader


class Holder:
    loader = load_as_of


@pytest.mark.parametrize("holder", [with_default, with_kw_default, Reader, Holder],
                         ids=["positional", "keyword-only", "method", "class attribute"])
def test_a_default_argument_is_a_stray_caller(monkeypatch: pytest.MonkeyPatch,
                                              holder: object) -> None:
    plant(monkeypatch, "fpl.planted_default", reader=holder)
    assert stray_callers() == ["fpl.planted_default"]


def read_through_the_module() -> object:
    """A caller that reaches the loader as `fpl.features.load_as_of(...)`."""
    return fpl.features.load_as_of("2025-2026", 5, "backtest")


def test_a_call_through_the_loaders_module_raises_inside_the_swap(tmp_path: Path) -> None:
    with synth_point(tmp_path / "data"):
        with pytest.raises(RuntimeError, match="bypassed the synthetic swap"):
            read_through_the_module()
        assert all(m.load_as_of is not load_as_of for m in CALLERS)  # the swap still holds
    assert fpl.features.load_as_of is load_as_of


def test_the_swap_reaches_every_caller_and_is_undone(tmp_path: Path) -> None:
    with synth_point(tmp_path / "data"):
        assert all(m.load_as_of is not load_as_of for m in CALLERS)
        assert stray_callers() == []
    assert all(m.load_as_of is load_as_of for m in CALLERS)
