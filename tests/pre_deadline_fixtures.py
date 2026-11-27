"""Fixtures shared by the pre-deadline builder's tests: a synthetic git repo and its config."""

from __future__ import annotations

from pathlib import Path

import pytest

import synth
import view_repo
from fpl.ingest import ROOT, load_config
from view_repo import Commit

SEASON = synth.SEASON


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[Commit]]:
    return view_repo.make_repo(tmp_path_factory.mktemp("view_repo"))


@pytest.fixture(scope="module")
def git_cfg(repo: tuple[Path, list[Commit]]) -> dict:
    """The synthetic season's config; the repo's 9 players are inside the row bounds."""
    base = {**load_config(ROOT / "config" / "pipeline.yaml"), "score_corrections": []}
    out = synth.synth_cfg(base, repo[0])
    out["seasons"] = [s for s in base["seasons"] if s["id"] == SEASON]
    out["validation"] = {**out["validation"], "players_rows_per_snapshot": [8, 9],
                         "playerstats_rows_snapshot": [8, 9]}
    return out
