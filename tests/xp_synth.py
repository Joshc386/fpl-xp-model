"""A test double for the xP harness's reads, on the synthetic upstream.

The harness reads only through `backtest.xp_inputs.read`, which looks `fpl.features.load_as_of`
up at each call; a real component imports it by name (the minutes component does).
`synth_reads` replaces both for the block with `SynthReads`: `fpl.features.load_as_of` and the
`load_as_of` of every module `elo_check_synth.callers()` finds. `SynthReads` reads the synthetic
season with its own validation bounds (the real config's bounds don't fit 4 clubs), from the
folder its `point` names: the double for `perturb.redirect`. Every call is recorded, so a test
can check which seasons and as-of gameweeks were read.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest import mock

import pandas as pd

import fpl.features
from elo_check_synth import callers, synth_cfg_for
from fpl.features import load_as_of


class SynthReads:
    """`load_as_of` over the synthetic data folder `data_dir`, recording every call."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.calls: list[tuple[str, int, str]] = []

    def __call__(self, season: str, as_of_gw: int, mode: str, **_: object
                 ) -> dict[str, pd.DataFrame]:
        self.calls.append((season, as_of_gw, mode))
        return load_as_of(season, as_of_gw, mode, cfg=synth_cfg_for(self.data_dir))

    @contextmanager
    def point(self, data_dir: Path) -> Iterator[None]:
        """Read `data_dir` inside the block (the stand-in for `perturb.redirect`)."""
        old, self.data_dir = self.data_dir, Path(data_dir)
        try:
            yield
        finally:
            self.data_dir = old


@contextmanager
def synth_reads(data_dir: Path) -> Iterator[SynthReads]:
    """Route `fpl.features.load_as_of`, and every module holding it by name, to the synthetic
    season for the block."""
    reads = SynthReads(data_dir)
    with ExitStack() as stack:
        for module in callers():
            stack.enter_context(mock.patch.object(module, "load_as_of", reads))
        stack.enter_context(mock.patch.object(fpl.features, "load_as_of", reads))
        yield reads
