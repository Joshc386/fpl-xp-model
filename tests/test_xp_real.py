"""The xP harness on real 2025/26 data (skipped when there is no upstream checkout).

About a minute: one perturbation case through the production `redirect` (the loader's
`use_data_copy`, the real config's validation), so the extended corruption is shown to leave an
honest read valid; and the snapshot-timing audit of three snapshots. Every read is checked to be
2025/26: this task never reads the holdout.
"""

from __future__ import annotations

import functools
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import numpy as np
import pytest
from backtest.elo_check import corruption, load_settings
from backtest.perturb import copy_upstream, redirect
from backtest.perturb_files import file_rules
from backtest.run_backtest import default_timing
from backtest.snapshot_timing import deadlines, snapshot_timing
from backtest.xp_inputs import baselines
from backtest.xp_leakage import peeking_baselines, perturbation_case

import fpl.features
from fpl.ingest import ROOT, load_config, upstream_data_dir
from fpl.view_checkout import copy_view

CFG = load_config(ROOT / "config" / "pipeline.yaml")
DATA = upstream_data_dir(CFG)
SEASON = "2025-2026"
S = load_settings()["xp_backtest"]

pytestmark = pytest.mark.skipif(
    not (DATA / SEASON / "By Gameweek" / "GW38").exists(), reason="no upstream checkout")


@pytest.fixture(autouse=True)
def development_window_only() -> Iterator[None]:
    """Fail any read of a season other than 2025/26."""
    real = fpl.features.load_as_of

    def guarded(season: str, *a: object, **kw: object) -> dict:
        assert season == SEASON, f"read {season}: this task never reads the holdout"
        return real(season, *a, **kw)

    with mock.patch.object(fpl.features, "load_as_of", guarded):
        yield


def test_a_real_case_leaves_the_baselines_alone_and_catches_the_planted_leak(
        tmp_path: Path) -> None:
    p = S["perturbation"]
    dst = tmp_path / "data"
    copy_upstream(DATA, dst, [SEASON], list(p["files"]))
    # A read inside the copy takes its view from the copy (the one built by fpl.pre_deadline).
    copy_view(ROOT / CFG["paths"]["pre_deadline_dir"], ROOT / CFG["upstream"]["checkout_path"],
              dst, [SEASON])
    fns = {"baselines": functools.partial(baselines, s=S, prem="prem"),
           "planted_leak": functools.partial(peeking_baselines, s=S, prem="prem")}
    out = perturbation_case(fns, SEASON, 20, DATA, dst, redirect, np.random.default_rng(3),
                            corruption({"perturbation": p}, CFG), file_rules(p["files"]),
                            "backtest", list(p["files"]), controls=["baselines"],
                            forbid=[DATA, ROOT / "data"])
    f = out["functions"]
    assert f["baselines"] == {"rows": f["baselines"]["rows"], "changed": 0, "error": None,
                              "by": None}
    assert f["baselines"]["rows"] > 500
    assert f["planted_leak"]["changed"] > 0
    assert out["control"]["baselines"]["changed"] > 0
    cells = out["corrupted_cells"]
    for name in ("results", "players", "playerstats", "player_gameweek_stats",
                 "playermatchstats", "shots", "incidents"):
        assert cells[name] > 0, name


def test_the_gw1_snapshot_is_late_and_its_ep_next_is_for_gw16() -> None:
    fx = fpl.features.load_as_of(SEASON, 38, "backtest")["fact_fixture"]
    dl = deadlines(fx, "prem", int(CFG["loader"]["deadline_offset_minutes"]))
    t = S["snapshot_timing"]
    got = snapshot_timing(ROOT / CFG["upstream"]["checkout_path"], CFG["upstream"]["data_dir"],
                          SEASON, dl, [1, 14, 15], t["fields"], float(t["late_share"]))
    got = got.set_index("snapshot")
    assert got.late.to_dict() == {1: True, 14: False, 15: False}
    assert got.loc[1, "refers_to"] == 16 and got.loc[1, "refers_share"] > 0.99
    assert got.loc[1, "last_write"] > dl[2]


def test_the_default_timing_hook_audits_each_target_gameweeks_snapshot() -> None:
    s = {**S, "seasons": [{"id": SEASON, "target_gameweeks": [2, 3]}]}
    finals = {SEASON: fpl.features.load_as_of(SEASON, 3, "backtest")}
    got = default_timing(CFG)(s, finals)
    assert got.snapshot.tolist() == [1, 2] and got.target.tolist() == [2, 3]
    assert (got.season == SEASON).all()
