"""The synthetic redirect's guard: no `fpl` or `backtest` module can bypass the swap."""

from __future__ import annotations

import importlib
import pkgutil
import sys
import types
from functools import partial
from pathlib import Path

import backtest
import pytest

import fpl
import fpl.features
import fpl.models.elo
import synth
from elo_check_synth import BASE_CFG, ELO_CALLERS, callers, stray_callers, synth_point
from fpl.features import load_as_of
from fpl.ingest import ROOT

SEASON = synth.SEASON


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
    assert holders - {"fpl.features"} == {m.__name__ for m in callers()}
    assert set(ELO_CALLERS) <= set(callers())


def plant(monkeypatch: pytest.MonkeyPatch, name: str, **attrs: object) -> None:
    module = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(module, k, v)
    monkeypatch.setitem(sys.modules, name, module)


@pytest.mark.parametrize("name", ["fpl.planted_caller", "backtest.planted_caller"])
def test_a_new_caller_under_its_own_name_is_found_and_swapped(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str) -> None:
    """A new component that imports `load_as_of` by name needs no edit to the guard."""
    plant(monkeypatch, name, load_as_of=load_as_of)
    plant(monkeypatch, "planted_outside", load_as_of=load_as_of)  # not fpl or backtest
    assert stray_callers() == []
    assert name in {m.__name__ for m in callers()}
    assert "planted_outside" not in {m.__name__ for m in callers()}
    with synth_point(tmp_path):
        assert sys.modules[name].load_as_of is not load_as_of
    assert sys.modules[name].load_as_of is load_as_of


def test_a_nested_block_re_points_every_caller_at_its_own_copy(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The perturbation's redirect enters the swap inside an outer one: the inner copy wins,
    and the outer swap is back on exit."""
    plant(monkeypatch, "fpl.planted_caller", load_as_of=load_as_of)
    module = sys.modules["fpl.planted_caller"]
    with synth_point(tmp_path / "outer" / "data"):
        outer = module.load_as_of
        with synth_point(tmp_path / "inner" / "data"):
            inner = module.load_as_of
            assert inner is not outer and inner.keywords != outer.keywords
            assert all(m.load_as_of is not outer for m in ELO_CALLERS)
        assert module.load_as_of is outer
    assert module.load_as_of is load_as_of


@pytest.mark.parametrize("name", ["fpl.planted_alias", "backtest.planted_alias"])
def test_an_alias_in_either_package_stops_the_synthetic_redirect(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str) -> None:
    """Both packages are guarded: dropping either from `PACKAGES` fails one case."""
    plant(monkeypatch, name, read_tables=load_as_of)
    plant(monkeypatch, "planted_outside", read_tables=load_as_of)  # not fpl or backtest
    assert stray_callers() == [name]
    with pytest.raises(RuntimeError, match=name), synth_point(tmp_path):
        pass


def test_an_aliased_import_is_a_stray_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    plant(monkeypatch, "backtest.planted_alias", read_tables=load_as_of)
    assert stray_callers() == ["backtest.planted_alias"]


def test_an_alias_inside_a_swapped_module_is_a_stray_caller(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Only a swapped module's own `load_as_of` name is swapped."""
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
        assert all(m.load_as_of is not load_as_of for m in ELO_CALLERS)  # the swap holds
    assert fpl.features.load_as_of is load_as_of


def test_the_swap_reaches_every_caller_and_is_undone(tmp_path: Path) -> None:
    with synth_point(tmp_path / "data"):
        assert all(m.load_as_of is not load_as_of for m in ELO_CALLERS)
        assert stray_callers() == []
    assert all(m.load_as_of is load_as_of for m in ELO_CALLERS)


# --- callers the identity scan can't see: `_resolve` is patched, so any of them raises ------

# An as-of no season has: before the patch, the real loader stops at it without reading data.
STRAY_READ = ("2025-2026", 99, "backtest")
REAL = "resolved to the real upstream checkout"


def make_closure() -> object:
    loader = load_as_of
    return lambda: loader(*STRAY_READ)


class Static:
    loader = staticmethod(load_as_of)

    @staticmethod
    def read(loader: object = load_as_of) -> object:
        return loader(*STRAY_READ)

    @classmethod
    def read_cls(cls, loader: object = load_as_of) -> object:
        return loader(*STRAY_READ)

    class Inner:
        loader = load_as_of


class Instance:
    def __init__(self) -> None:
        self.loader = load_as_of


HIDDEN = {  # name -> (what the module holds, how a caller reaches the loader through it)
    "dict": ({"f": load_as_of}, lambda h: h["f"](*STRAY_READ)),
    "tuple": ((load_as_of,), lambda h: h[0](*STRAY_READ)),
    "partial": (partial(load_as_of, mode="backtest"), lambda h: h(*STRAY_READ[:2])),
    "closure": (make_closure(), lambda h: h()),
    "staticmethod": (Static, lambda h: h.loader(*STRAY_READ)),
    "staticmethod default": (Static, lambda h: h.read()),
    "classmethod default": (Static, lambda h: h.read_cls()),
    "nested class": (Static, lambda h: h.Inner.loader(*STRAY_READ)),
    "instance attribute": (Instance(), lambda h: h.loader(*STRAY_READ)),
}


@pytest.mark.parametrize("kind", list(HIDDEN))
def test_a_caller_the_scan_misses_still_raises_inside_the_swap(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str) -> None:
    held, call = HIDDEN[kind]
    plant(monkeypatch, "fpl.planted_hidden", held=held)
    assert stray_callers() == []  # the identity scan can't see it
    with synth_point(tmp_path / "data"), pytest.raises(RuntimeError, match=REAL):
        call(held)
    with pytest.raises(ValueError, match="as_of_gw must be"):  # outside, the real loader again
        call(held)


@pytest.mark.parametrize("module", ELO_CALLERS, ids=lambda m: m.__name__)
def test_every_swapped_caller_still_reads_the_synthetic_season(
        synth_upstream: tuple[Path, dict], module: types.ModuleType) -> None:
    with synth_point(synth_upstream[0] / "data"):
        tables = module.load_as_of(SEASON, 3, "backtest")
    fx = tables["fact_fixture"]
    assert set(fx.season) == {SEASON} and fx[fx.finished].gw.max() == 3
    assert len(tables["dim_team"]) == len(synth.TEAM_CODE)


@pytest.mark.parametrize("given", [{"root": ROOT}, {"cfg": BASE_CFG}], ids=["root", "cfg"])
def test_a_read_given_the_real_root_or_config_raises_inside_the_swap(tmp_path: Path,
                                                                     given: dict) -> None:
    with synth_point(tmp_path / "data"), pytest.raises(RuntimeError, match=REAL):
        load_as_of(*STRAY_READ, **given)


def test_the_live_readers_are_guarded_too(tmp_path: Path) -> None:
    """`_resolve` serves `live_deadlines` and `live_gameweeks` as well as `load_as_of`."""
    with synth_point(tmp_path / "data"), pytest.raises(RuntimeError, match=REAL):
        fpl.features.live_deadlines(SEASON)
