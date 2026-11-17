"""Shared fixtures: the pipeline config, the real-upstream samples, the synthetic season
(`synth_upstream`, `synth_load`) and the Elo check's honest run on it (`honest_run`, `honest`)."""

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
    """The real pipeline config, without score corrections.

    The sample data is a cut of upstream that does not hold the corrected match (rule 16);
    tests/test_score_corrections.py covers the function, test_score_corrections_config.py the
    entries, and test_score_corrections_real.py the loader on the real checkout.
    """
    return {**load_config(ROOT / "config" / "pipeline.yaml"), "score_corrections": []}


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


@pytest.fixture(scope="session")
def honest_run(synth_upstream: tuple[Path, dict]) -> tuple[dict, list[Path]]:
    """The Elo check on the synthetic season with the real model and no `point`, so through the
    production `perturb.redirect`, and the data copies that redirect was pointed at. Session
    scope: several test files render it (copy it before changing it)."""
    from backtest.elo_check import Models, run_check

    from elo_check_runs import settings
    from elo_check_synth import real_redirect_to_synth, synth_point

    root, cfg = synth_upstream
    seen: list[Path] = []
    with synth_point(root / "data"), real_redirect_to_synth(seen):
        return run_check(settings(), Models(), cfg, root / "data"), seen


@pytest.fixture(scope="session")
def honest(honest_run: tuple[dict, list[Path]]) -> dict:
    """The honest run's results (copy them before changing them)."""
    return honest_run[0]
