"""A test double for the Elo check's redirect, for the synthetic upstream.

The harness points the model at a data copy with the loader's `use_data_copy`, which swaps the
data folder but keeps the real config, whose validation bounds the 4-club synthetic season
can't meet. So the synthetic tests point each module's `load_as_of` at the copy with the
synthetic bounds instead: the model's (as its own synthetic tests do) and the harness's. No
loader function is patched. `tests/test_elo_check_real.py` exercises `use_data_copy` itself.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from functools import partial
from pathlib import Path
from unittest import mock

import backtest.elo_check
import backtest.elo_leakage

import fpl.models.elo
import synth
from fpl.features import load_as_of
from fpl.ingest import ROOT, load_config

BASE_CFG = load_config(ROOT / "config" / "pipeline.yaml")
CALLERS = (fpl.models.elo, backtest.elo_check, backtest.elo_leakage)


def synth_cfg_for(data_dir: Path) -> dict:
    """The synthetic config pointed at `data_dir` (a folder named `data` in a checkout)."""
    return synth.synth_cfg(BASE_CFG, data_dir.parent)


@contextmanager
def synth_point(data_dir: Path) -> Iterator[None]:
    """Every `load_as_of` call by the model or the harness reads `data_dir` as synthetic data."""
    load = partial(load_as_of, cfg=synth_cfg_for(data_dir))
    with ExitStack() as stack:
        for module in CALLERS:
            stack.enter_context(mock.patch.object(module, "load_as_of", load))
        yield
