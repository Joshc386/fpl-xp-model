"""A test double for the Elo check's redirect, for the synthetic upstream.

The harness points the model at a data copy with the loader's `use_data_copy`, which swaps the
data folder but keeps the real config, whose validation bounds the 4-club synthetic season
can't meet. So the synthetic tests point each module's `load_as_of` at the copy with the
synthetic bounds instead: the model's (as its own synthetic tests do) and the harness's. The
loader's own `fpl.features.load_as_of` is replaced by a function that raises, so a caller that
reaches it through the module (`features.load_as_of(...)`) fails instead of reading the real
checkout; the swapped callers' partial holds the original. `use_data_copy` is never patched.
`tests/test_elo_check_real.py` exercises it.

The callers are found, not listed: `callers()` is every loaded `fpl` or `backtest` module
(other than the loader) whose own `load_as_of` is the real loader, so a new model component
that imports it by name is swapped with no edit here (decided 2026-11-23, when the minutes
component arrived). `synth_point` first checks that no loaded module holds the real
`load_as_of` anywhere the swap doesn't reach: under another name (an aliased import) or as a
default argument or class attribute. Such a caller would bypass the swap and silently read the
real checkout. A module first imported inside the block isn't swapped; it reaches the patched
`_resolve` below and fails. The scan names the module up
front but can't see every hiding place (a dict, a partial, a closure, a nested class...), so
`fpl.features._resolve`, which `load_as_of`, `live_deadlines` and `live_gameweeks` look up at
each call, is also patched to raise when it resolves to the real checkout's data folder:
whatever holds the real loader, and whatever `cfg` or `root` it passes, only the synthetic
config gets through. The swapped callers pass it.
"""

from __future__ import annotations

import inspect
import sys
import types
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from functools import partial
from pathlib import Path
from typing import NoReturn
from unittest import mock

import backtest.elo_check
import backtest.elo_leakage
import backtest.perturb

import fpl.features
import fpl.models.elo
import fpl.models.elo_tune
import synth
from fpl.features import load_as_of
from fpl.ingest import ROOT, load_config, upstream_data_dir

# Without score corrections: the synthetic data is a cut that lacks the corrected match (rule 16).
BASE_CFG = {**load_config(ROOT / "config" / "pipeline.yaml"), "score_corrections": []}
# The Elo check's own callers, imported above so they are always found and swapped. The tuner
# isn't on the check's path; it is swapped anyway, as every holder is.
ELO_CALLERS = (fpl.models.elo, fpl.models.elo_tune, backtest.elo_check, backtest.elo_leakage)
PACKAGES = ("fpl", "backtest")


def synth_cfg_for(data_dir: Path) -> dict:
    """The synthetic config pointed at `data_dir` (a folder named `data` in a checkout)."""
    return synth.synth_cfg(BASE_CFG, data_dir.parent)


def _held(value: object) -> list[object]:
    """`value`, a class's attributes, and the default arguments of the functions among them."""
    inner = list(vars(value).values()) if inspect.isclass(value) else []
    fns = [v for v in (value, *inner) if inspect.isfunction(v)]
    defaults = [d for f in fns
                for d in (*(f.__defaults__ or ()), *(f.__kwdefaults__ or {}).values())]
    return [value, *inner, *defaults]


def _bypasses(module: types.ModuleType, swapped: bool) -> bool:
    """Whether `module` holds the real `load_as_of` where the swap misses it (compared by
    identity). In a swapped module, its own `load_as_of` attribute is the one swapped."""
    return any(held is load_as_of for name, value in vars(module).items()
               if not (swapped and name == "load_as_of") for held in _held(value))


def _loaded() -> list[tuple[str, types.ModuleType]]:
    return sorted((name, m) for name, m in list(sys.modules.items())
                  if name.split(".")[0] in PACKAGES and isinstance(m, types.ModuleType))


SWAP_MARK = "_synth_swap"


def _swappable(value: object) -> bool:
    """The real loader, or a swap an enclosing `synth_point` put there (blocks nest: the
    perturbation's redirect re-points the callers at its copy inside an outer block)."""
    return value is load_as_of or getattr(value, SWAP_MARK, False)


def callers() -> tuple[types.ModuleType, ...]:
    """Every loaded `fpl` and `backtest` module but the loader whose own `load_as_of` is the
    real loader (or an enclosing block's swap): the modules `synth_point` swaps."""
    return tuple(m for name, m in _loaded()
                 if name != "fpl.features" and _swappable(getattr(m, "load_as_of", None)))


def stray_callers() -> list[str]:
    """Loaded `fpl` and `backtest` modules that hold the real `load_as_of` where the swap
    misses it: under any name but their own `load_as_of`, or held inside a value."""
    return [name for name, module in _loaded() if _bypasses(module, True)]


REAL_DATA = upstream_data_dir(BASE_CFG, ROOT).resolve()


def _guarded(resolve: Callable[..., tuple[dict, Path]]) -> Callable[..., tuple[dict, Path]]:
    """`fpl.features._resolve` that raises when it resolves to the real checkout's data."""
    def guarded(cfg: dict | None, root: Path | None) -> tuple[dict, Path]:
        out = resolve(cfg, root)
        if out[1].resolve() == REAL_DATA:
            raise RuntimeError(f"a data read inside the synthetic swap resolved to the real "
                               f"upstream checkout ({REAL_DATA}): the caller bypassed the swap")
        return out

    return guarded


def _bypassed(*args: object, **kwargs: object) -> NoReturn:
    raise RuntimeError("fpl.features.load_as_of was called directly: the caller bypassed the "
                       "synthetic swap (it reaches the loader through its module)")


@contextmanager
def synth_point(data_dir: Path) -> Iterator[None]:
    """Every `load_as_of` call by the model or the harness reads `data_dir` as synthetic data.

    Raises `RuntimeError` if a module holds `load_as_of` where the swap misses it (import it
    by its own name instead), and, inside, on any call through `fpl.features`
    and on any read that resolves to the real checkout's data, however the caller holds the
    loader and whatever `cfg` or `root` it passes.
    """
    if stray := stray_callers():
        raise RuntimeError(f"load_as_of held where the synthetic swap can't reach it: {stray}")
    load = partial(load_as_of, cfg=synth_cfg_for(data_dir))
    setattr(load, SWAP_MARK, True)
    with ExitStack() as stack:
        for module in callers():
            stack.enter_context(mock.patch.object(module, "load_as_of", load))
        stack.enter_context(mock.patch.object(fpl.features, "load_as_of", _bypassed))
        stack.enter_context(mock.patch.object(fpl.features, "_resolve",
                                              _guarded(fpl.features._resolve)))
        yield


@contextmanager
def real_redirect_to_synth(seen: list[Path]) -> Iterator[None]:
    """Let the production `perturb.redirect` reach the synthetic copy, recording each copy.

    Only `perturb`'s reference to the loader's `use_data_copy` is replaced, by `synth_point`;
    `redirect` itself and every default that names it stay the real ones, so a run that gets
    no `point` uses the production wiring.
    """
    def data_copy(data_dir: Path) -> AbstractContextManager[None]:
        seen.append(Path(data_dir))
        return synth_point(Path(data_dir))

    with mock.patch.object(backtest.perturb, "use_data_copy", data_copy):
        yield
