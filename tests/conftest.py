"""Shared fixtures: the pipeline config and the real-upstream samples."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path

import pytest

import synth
from fpl.features import load_as_of
from fpl.ingest import RawSeason, load_config, read_season

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DATA = Path(__file__).parent / "fixtures" / "upstream" / "data"

SAMPLE_SEASONS = {
    "2025-2026": {"id": "2025-2026", "gameweeks": 2, "tackles_column": "tackles"},
    "2026-2027": {"id": "2026-2027", "gameweeks": 3, "tackles_column": "tackles_won"},
}


PREM = "prem"
OFFSET = 90


def read_sample(
    data_dir: Path, season_cfg: dict, commit: str = "x", as_of_gw: int | None = None
) -> RawSeason:
    """read_season with the config's Premier League tag and deadline offset."""
    return read_season(
        data_dir, season_cfg, commit, as_of_gw, prem_tag=PREM, offset_minutes=OFFSET
    )


@pytest.fixture(scope="session")
def cfg() -> dict:
    """The real pipeline config."""
    return load_config(ROOT / "config" / "pipeline.yaml")


@pytest.fixture(scope="session")
def _raw_2627() -> RawSeason:
    return read_sample(SAMPLE_DATA, SAMPLE_SEASONS["2026-2027"], commit="sample")


@pytest.fixture(scope="session")
def _raw_2526() -> RawSeason:
    return read_sample(SAMPLE_DATA, SAMPLE_SEASONS["2025-2026"], commit="sample")


@pytest.fixture
def raw_2627(_raw_2627: RawSeason) -> RawSeason:
    """Sample 2026-2027 season (GW1-2 played, GW3 not yet), safe to mutate."""
    return copy.deepcopy(_raw_2627)


@pytest.fixture
def raw_2526(_raw_2526: RawSeason) -> RawSeason:
    """Sample 2025-2026 season (GW1-2 played), safe to mutate."""
    return copy.deepcopy(_raw_2526)


@pytest.fixture(scope="session")
def synth_upstream(tmp_path_factory: pytest.TempPathFactory, cfg: dict) -> tuple[Path, dict]:
    """A synthetic 38-gameweek upstream checkout (read-only) and a config pointing at it."""
    root = tmp_path_factory.mktemp("synth_upstream")
    synth.write_upstream(root / "data")
    return root, synth.synth_cfg(cfg, root)


@pytest.fixture(scope="session")
def synth_load(synth_upstream: tuple[Path, dict]) -> Callable[[int, str], dict]:
    """load_as_of on the synthetic season, memoised for the session (do not modify results)."""
    cache: dict[tuple[int, str], dict] = {}

    def load(as_of: int, mode: str = "backtest") -> dict:
        if (as_of, mode) not in cache:
            cache[(as_of, mode)] = load_as_of(synth.SEASON, as_of, mode, cfg=synth_upstream[1])
        return cache[(as_of, mode)]

    return load
