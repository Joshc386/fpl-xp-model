"""A test double for the Elo check's redirect, for the synthetic upstream.

The harness points the model at a data copy with the loader's `use_data_copy`, which swaps the
data folder but keeps the real config, whose validation bounds the 4-club synthetic season
can't meet. So the synthetic tests point each module's `load_as_of` at the copy with the
synthetic bounds instead: the model's (as its own synthetic tests do) and the harness's. No
loader function is patched. `tests/test_elo_check_real.py` exercises `use_data_copy` itself.

`CALLERS` is listed by hand, so `synth_point` first checks that no other loaded `fpl` or
`backtest` module holds its own reference to `load_as_of`: such a caller would bypass the swap
and silently read the real checkout.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from functools import partial
from pathlib import Path
from unittest import mock

import backtest.elo_check
import backtest.elo_leakage
import backtest.perturb

import fpl.models.elo
import fpl.models.elo_tune
import synth
from fpl.features import load_as_of
from fpl.ingest import ROOT, load_config

BASE_CFG = load_config(ROOT / "config" / "pipeline.yaml")
# Every module that imports `load_as_of` by name. The tuner isn't on the check's path; it is
# swapped anyway so the rule stays "every holder is swapped".
CALLERS = (fpl.models.elo, fpl.models.elo_tune, backtest.elo_check, backtest.elo_leakage)
PACKAGES = ("fpl", "backtest")


def synth_cfg_for(data_dir: Path) -> dict:
    """The synthetic config pointed at `data_dir` (a folder named `data` in a checkout)."""
    return synth.synth_cfg(BASE_CFG, data_dir.parent)


def stray_callers() -> list[str]:
    """Loaded `fpl` and `backtest` modules, other than `CALLERS` and the loader's own, that
    hold a reference to the real `load_as_of`: the swap would miss them."""
    listed = {m.__name__ for m in CALLERS} | {"fpl.features"}
    return sorted(name for name, module in list(sys.modules.items())
                  if name.split(".")[0] in PACKAGES and name not in listed
                  and getattr(module, "load_as_of", None) is load_as_of)


@contextmanager
def synth_point(data_dir: Path) -> Iterator[None]:
    """Every `load_as_of` call by the model or the harness reads `data_dir` as synthetic data.

    Raises `RuntimeError` if a module outside `CALLERS` holds `load_as_of` (add it there).
    """
    if stray := stray_callers():
        raise RuntimeError(f"load_as_of callers missing from CALLERS: {stray}")
    load = partial(load_as_of, cfg=synth_cfg_for(data_dir))
    with ExitStack() as stack:
        for module in CALLERS:
            stack.enter_context(mock.patch.object(module, "load_as_of", load))
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
