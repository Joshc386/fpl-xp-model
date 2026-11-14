"""`use_data_copy`: loader reads come from another data folder inside the block only.

The file readers are replaced by recorders, so these tests need no upstream data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from fpl import features
from fpl.features import live_deadlines, live_gameweeks, load_as_of, use_data_copy
from fpl.ingest import ROOT, load_config, upstream_data_dir

CFG = load_config(ROOT / "config" / "pipeline.yaml")
CHECKOUT = upstream_data_dir(CFG)
SEASON = "2026-2027"
COPY = Path("somewhere") / "copy" / "data"


class Stop(Exception):
    """Raised by the recording reader to end `load_as_of` after the folder is known."""


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Folders the loader's readers were asked for, in order."""
    out: list[Path] = []

    def read_deadlines(season_dir: Path) -> pd.DataFrame:
        out.append(season_dir)
        times = pd.date_range("2026-08-01T10:00:00Z", periods=38, freq="7D")
        return pd.DataFrame({"id": range(1, 39), "deadline_time": times.strftime(
            "%Y-%m-%dT%H:%M:%S+00:00")})

    def read_season(data_dir: Path, *args: object, **kwargs: object) -> None:
        out.append(data_dir)
        raise Stop

    monkeypatch.setattr(features, "read_deadlines", read_deadlines)
    monkeypatch.setattr(features, "read_season", read_season)
    return out


def read_all() -> None:
    """One call of each loader function with no root or cfg."""
    live_deadlines(SEASON)
    live_gameweeks(SEASON, datetime(2026, 9, 1, tzinfo=UTC))
    with pytest.raises(Stop):
        load_as_of(SEASON, 3, "backtest")


def test_outside_the_block_reads_come_from_the_checkout(seen: list[Path]) -> None:
    read_all()
    assert seen == [CHECKOUT / SEASON, CHECKOUT / SEASON, CHECKOUT]


def test_inside_the_block_every_loader_function_reads_the_copy(seen: list[Path]) -> None:
    with use_data_copy(COPY):
        read_all()
    assert seen == [COPY / SEASON, COPY / SEASON, COPY]


def test_the_checkout_is_back_after_the_block_and_after_an_exception(seen: list[Path]) -> None:
    with use_data_copy(COPY):
        pass
    with pytest.raises(RuntimeError), use_data_copy(COPY):
        raise RuntimeError("boom")
    live_deadlines(SEASON)
    assert seen == [CHECKOUT / SEASON]


def test_blocks_nest_and_restore_the_outer_copy(seen: list[Path]) -> None:
    inner = Path("inner")
    with use_data_copy(COPY):
        with use_data_copy(inner):
            live_deadlines(SEASON)
        live_deadlines(SEASON)
    assert seen == [inner / SEASON, COPY / SEASON]


def test_an_explicit_root_or_cfg_wins_over_the_copy(seen: list[Path]) -> None:
    other = Path("other_root")
    cfg = {**CFG, "upstream": {**CFG["upstream"], "checkout_path": "elsewhere"}}
    with use_data_copy(COPY):
        live_deadlines(SEASON, root=ROOT)
        live_deadlines(SEASON, cfg=cfg)
        with pytest.raises(Stop):
            load_as_of(SEASON, 3, "backtest", cfg=cfg)
        live_deadlines(SEASON, cfg=CFG, root=other)
    assert seen == [CHECKOUT / SEASON, ROOT / "elsewhere" / "data" / SEASON,
                    ROOT / "elsewhere" / "data", upstream_data_dir(CFG, other) / SEASON]


def test_a_patched_private_config_still_works(seen: list[Path], monkeypatch: pytest.MonkeyPatch
                                              ) -> None:
    # The validator's harness patches `features._config`; that must keep taking effect.
    cfg = {**CFG, "upstream": {**CFG["upstream"], "checkout_path": "patched"}}
    monkeypatch.setattr(features, "_config", lambda c, r: c if c is not None else cfg)
    live_deadlines(SEASON)
    assert seen == [ROOT / "patched" / "data" / SEASON]
