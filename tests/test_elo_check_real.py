"""The perturbation case on a real data copy through the loader's `use_data_copy` (skipped
when there is no upstream checkout). About 30 s: one case, ten reads. It reads the real config,
so the control's corruption up to the as-of must leave the score-corrected match alone."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from backtest.elo_check import corruption, load_settings
from backtest.elo_leakage import after_as_of_case, peeking_goals
from backtest.perturb import copy_upstream, redirect

from fpl.ingest import ROOT, load_config, upstream_data_dir
from fpl.models.elo import elo_ratings
from fpl.models.team_goals import elo_goals
from fpl.view_checkout import copy_view

CFG = load_config(ROOT / "config" / "pipeline.yaml")
DATA = upstream_data_dir(CFG)
SEASON = "2025-2026"
# The files the harness copies into its scratch upstream copy, from backtest/config.yaml, so a
# file the loader starts reading (shots and incidents, phase 2 task 1) needs no edit here.
FILES = load_settings()["upstream_files"]

pytestmark = pytest.mark.skipif(
    not (DATA / SEASON / "By Gameweek" / "GW38").exists(), reason="no upstream checkout")


def test_a_real_case_passes_reaches_the_copy_and_catches_the_planted_leak(
        tmp_path: Path) -> None:
    dst = tmp_path / "data"
    copy_upstream(DATA, dst, [SEASON], FILES)
    # A read inside the copy takes its view from the copy (the one built by fpl.pre_deadline).
    copy_view(ROOT / CFG["paths"]["pre_deadline_dir"], ROOT / CFG["upstream"]["checkout_path"],
              dst, [SEASON])
    c = corruption(load_settings(), CFG)  # keeps the score-corrected match (data rule 16)
    assert c.keep
    fns = {"elo_ratings": elo_ratings, "elo_goals": elo_goals, "planted_leak": peeking_goals}
    out = after_as_of_case(fns, SEASON, 33, DATA, dst, redirect, np.random.default_rng(11), c,
                           "backtest", controls=["elo_ratings", "elo_goals"])
    f, ctl = out["functions"], out["control"]
    assert f["elo_ratings"]["changed"] == 0 and f["elo_goals"]["changed"] == 0
    assert f["planted_leak"]["changed"] > 0
    assert ctl["elo_ratings"]["changed"] > 0 and ctl["elo_goals"]["changed"] > 0
