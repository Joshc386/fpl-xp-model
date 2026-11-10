"""Shared fixtures: the pipeline config and the real-upstream samples."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from fpl.ingest import RawSeason, load_config, read_season

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DATA = Path(__file__).parent / "fixtures" / "upstream" / "data"

SAMPLE_SEASONS = {
    "2025-2026": {"id": "2025-2026", "gameweeks": 2, "tackles_column": "tackles"},
    "2026-2027": {"id": "2026-2027", "gameweeks": 3, "tackles_column": "tackles_won"},
}


@pytest.fixture(scope="session")
def cfg() -> dict:
    """The real pipeline config."""
    return load_config(ROOT / "config" / "pipeline.yaml")


@pytest.fixture(scope="session")
def _raw_2627() -> RawSeason:
    return read_season(SAMPLE_DATA, SAMPLE_SEASONS["2026-2027"], commit="sample")


@pytest.fixture(scope="session")
def _raw_2526() -> RawSeason:
    return read_season(SAMPLE_DATA, SAMPLE_SEASONS["2025-2026"], commit="sample")


@pytest.fixture
def raw_2627(_raw_2627: RawSeason) -> RawSeason:
    """Sample 2026-2027 season (GW1-2 played, GW3 not yet), safe to mutate."""
    return copy.deepcopy(_raw_2627)


@pytest.fixture
def raw_2526(_raw_2526: RawSeason) -> RawSeason:
    """Sample 2025-2026 season (GW1-2 played), safe to mutate."""
    return copy.deepcopy(_raw_2526)
