"""The xP leakage checks on the synthetic season: the perturbation over every file, the planted
leak, a leak through a future club, the static read check and the refit check."""

from __future__ import annotations

import functools
import os
import sys
import threading
from pathlib import Path
from textwrap import dedent

import numpy as np
import pandas as pd
import pytest
from backtest.elo_check import load_settings
from backtest.elo_data import HarnessError
from backtest.perturb import Corruption, copy_upstream
from backtest.perturb_files import file_rules
from backtest.run_backtest import leakage_met
from backtest.xp_inputs import baselines, read
from backtest.xp_leakage import (
    changed_cells,
    peeking_baselines,
    perturbation_case,
    refit_findings,
)
from backtest.xp_reads import static_findings

import synth
from elo_check_synth import synth_cfg_for
from fpl.features import load_as_of
from test_xp_perturb_files import FILES, RULES
from xp_synth import synth_reads

SEASON = synth.SEASON
C = Corruption((0, 9), (1200.0, 2200.0), (0.0, 4.0), "prem", 90)
S = load_settings()["xp_backtest"]
HONEST = functools.partial(baselines, s=S, prem="prem")
LEAKY = functools.partial(peeking_baselines, s=S, prem="prem")


def future_club(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
    """A leak through a later snapshot's clubs (as with a transfer known early)."""
    out = HONEST(season, as_of_gw, mode)
    later = read(season, 38, mode)["dim_player"].set_index("player_id").team_id
    return out.assign(team_id=out.player_id.map(later))


@pytest.fixture
def case_dirs(synth_upstream: tuple[Path, dict], tmp_path: Path) -> tuple[Path, Path]:
    src = synth_upstream[0] / "data"
    dst = tmp_path / "data"
    copy_upstream(src, dst, [SEASON], FILES)
    return src, dst


def run_case(case_dirs: tuple[Path, Path], fns: dict, controls: list[str]) -> dict:
    src, dst = case_dirs
    with synth_reads(dst) as reads:
        return perturbation_case(fns, SEASON, 12, src, dst, reads.point,
                                 np.random.default_rng(7), C, RULES, "backtest", FILES,
                                 controls=controls, forbid=[src])


def test_honest_baselines_pass_and_the_planted_and_club_leaks_are_caught(
        case_dirs: tuple[Path, Path]) -> None:
    out = run_case(case_dirs, {"baselines": HONEST, "planted_leak": LEAKY,
                               "future_club": future_club}, ["baselines"])
    fns = out["functions"]
    assert fns["baselines"]["changed"] == 0 and fns["baselines"]["error"] is None
    assert fns["planted_leak"]["changed"] > 0
    assert fns["future_club"]["changed"] > 0
    assert out["control"]["baselines"]["changed"] > 0
    assert out["corrupted_cells"]["player_gameweek_stats"] > 0
    # The copy is restored: a second honest run on it equals the first.
    src, dst = case_dirs
    for name in ("matches", "player_gameweek_stats"):
        a = (src / SEASON / "By Gameweek" / "GW20" / f"{name}.csv").read_bytes()
        assert (dst / SEASON / "By Gameweek" / "GW20" / f"{name}.csv").read_bytes() == a


def test_a_function_that_fails_on_the_clean_copy_is_a_finding(
        case_dirs: tuple[Path, Path]) -> None:
    def reads_master(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
        raise FileNotFoundError("playerstats.csv")  # what a master read on the copy gives

    out = run_case(case_dirs, {"master": reads_master}, [])
    got = out["functions"]["master"]
    assert got["changed"] is None and "FileNotFoundError" in got["error"]


def test_static_findings_flag_every_way_round_the_loader(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = tmp_path / "xpstatic"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "ok.py").write_text(dedent("""        from fpl.features import load_as_of
        from fpl.ingest import ROOT, load_config
        def f(s, g, m):
            return load_as_of(s, g, m)
        """), encoding="utf-8")
    (pkg / "helper.py").write_text(dedent("""        import pandas as pd
        def h():
            return pd.read_csv('x.csv')
        """), encoding="utf-8")  # imported by bad.py: scanned through the import
    (pkg / "bad.py").write_text(dedent("""        import csv, subprocess
        from fpl.master import read_master_state
        from fpl.features import load_as_of as peek
        from backtest.snapshot_timing import snapshot_timing
        import xpstatic.helper
        def f(p, s, g, m, c):
            open(p)
            p.read_text()
            csv.reader(p)
            return peek(s, g + 1, m, cfg=c), fpl.features.load_as_of(s, g, m, root=p)
        """), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    got, scanned = static_findings([pkg / "ok.py", pkg / "bad.py"],
                                   S["static_check"]["forbidden"],
                                   follow=["xpstatic", "fpl.models"], trusted=["fpl.features"])
    assert {p.name for p in scanned} == {"ok.py", "bad.py", "helper.py"}
    assert got == [
        "bad.py:1: subprocess", "bad.py:2: fpl.master", "bad.py:2: read_master_state",
        "bad.py:3: load_as_of imported as peek", "bad.py:4: backtest.snapshot_timing",
        "bad.py:7: open", "bad.py:8: read_text", "bad.py:9: reader",
        "bad.py:10: load_as_of(cfg=)", "bad.py:10: load_as_of(root=)",
        "helper.py:3: read_csv"]


def direct_read(src: Path) -> object:
    """Reads the next gameweek's FPL points straight from the real data folder."""
    def predict(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
        out = HONEST(season, as_of_gw, mode)
        path = src / season / "By Gameweek" / f"GW{as_of_gw + 1}" / "player_gameweek_stats.csv"
        pts = pd.read_csv(path).set_index("id").event_points
        return out.assign(last5=out.player_id.map(pts).fillna(0.0))
    return predict


def given_config(src: Path) -> object:
    """Reads the next gameweek through the loader, given the real data's own config."""
    def predict(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
        out = HONEST(season, as_of_gw, mode)
        later = load_as_of(season, as_of_gw + 1, mode, cfg=synth_cfg_for(src))
        pgs = later["fact_player_gw"]
        pts = pgs[pgs.gw == as_of_gw + 1].set_index("player_id").points
        return out.assign(last5=out.player_id.map(pts).fillna(0.0))
    return predict


def swallowing(src: Path) -> object:
    """The direct read, with the guard's error caught and ignored."""
    inner = direct_read(src)

    def predict(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
        try:
            return inner(season, as_of_gw, mode)
        except Exception:
            return HONEST(season, as_of_gw, mode)
    return predict


def test_reads_that_bypass_the_scratch_copy_fail_the_perturbation(
        case_dirs: tuple[Path, Path]) -> None:
    src, _ = case_dirs
    fns = {"direct": direct_read(src), "given_cfg": given_config(src),
           "swallowed": swallowing(src)}
    out = run_case(case_dirs, fns, list(fns))
    for name in fns:
        got = out["functions"][name]
        assert got["changed"] is None and "outside the scratch copy" in got["error"], name
    assert leakage_met({"cases": [out], "static": []}, list(fns), {})["perturbation"] is False


def test_a_harness_error_inside_a_case_stops_it(case_dirs: tuple[Path, Path]) -> None:
    def broken(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
        raise HarnessError("pre-deadline view isn't wired in")

    with pytest.raises(HarnessError, match="pre-deadline view"):
        run_case(case_dirs, {"broken": broken}, [])


def test_refit_findings_flag_a_forecast_that_never_moves() -> None:
    def out(vals: dict[int, float]) -> pd.DataFrame:
        return pd.DataFrame({"player_id": 1, "gw": list(vals), "xp_total": list(vals.values())})

    moving = {3: out({4: 1.0, 5: 2.0}), 4: out({5: 2.5, 6: 1.0})}
    frozen = {3: out({4: 1.0, 5: 2.0}), 4: out({5: 2.0, 6: 1.0}), 5: out({6: 1.0})}
    assert refit_findings(moving, "xp_total") == ([], 1)
    assert refit_findings(frozen, "xp_total") == (["as-of 3 to 4", "as-of 4 to 5"], 2)
    assert refit_findings({3: out({4: 1.0})}, "xp_total") == ([], 0)


def test_rules_come_from_the_settings_shape() -> None:
    rules = file_rules({"players": {"keys": ["player_id"], "club": ["team_code"]}})
    assert rules["players"].club == frozenset({"team_code"})


def test_changed_cells_treats_nulls_of_any_kind_as_equal() -> None:
    a = pd.DataFrame({"x": pd.array([1, None, 3], dtype="Int64"), "y": [0.5, np.nan, 1.0]})
    assert changed_cells(a, a.copy()) == 0
    b = a.assign(x=pd.array([1, 2, 3], dtype="Int64"), y=[0.5, np.nan, 2.0])
    assert changed_cells(a, b) == 2
    assert changed_cells(a, a.iloc[:2]) == 6


def test_a_function_that_never_reads_the_copy_fails_copy_reached(
        case_dirs: tuple[Path, Path]) -> None:
    def constant(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
        return pd.DataFrame({"player_id": [1, 2], "xp_total": [1.0, 2.0]})

    out = run_case(case_dirs, {"baselines": HONEST, "constant": constant,
                               "planted_leak": LEAKY}, ["baselines", "constant"])
    assert out["control"]["constant"] == {"rows": 2, "changed": 0, "error": None, "by": None}
    assert out["control"]["baselines"]["by"] in ("value", "error")
    met = leakage_met({"cases": [out], "static": []}, ["baselines", "constant"], {})
    assert met["copy_reached"] is False and met["perturbation"] is True
    assert leakage_met({"cases": [out], "static": []}, ["baselines"], {})["copy_reached"]


def in_a_thread(src: Path) -> object:
    """The direct read, done in a new thread."""
    def predict(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
        got: dict = {}
        path = src / season / "By Gameweek" / f"GW{as_of_gw + 1}" / "player_gameweek_stats.csv"
        worker = threading.Thread(target=lambda: got.update(pts=pd.read_csv(path)))
        worker.start()
        worker.join()
        out = HONEST(season, as_of_gw, mode)
        if "pts" not in got:
            return out
        pts = got["pts"].set_index("id").event_points
        return out.assign(last5=out.player_id.map(pts).fillna(0.0))
    return predict


def make_link(link: Path, target: Path) -> None:
    """A directory junction on Windows (no admin rights needed), a symlink elsewhere."""
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_reads_from_a_thread_or_through_a_link_are_caught(case_dirs: tuple[Path, Path],
                                                          tmp_path: Path) -> None:
    src, _ = case_dirs
    link = tmp_path / "link_to_real_data"
    make_link(link, src)
    try:
        fns = {"thread": in_a_thread(src), "link": direct_read(link)}
        out = run_case(case_dirs, fns, list(fns))  # the worker's refusal is expected
    finally:
        os.rmdir(link) if sys.platform == "win32" else link.unlink()
    for name in fns:
        got = out["functions"][name]
        assert got["changed"] is None and "outside the scratch copy" in got["error"], name


def test_static_findings_follow_relative_imports(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = tmp_path / "xprel"
    (pkg / "sub").mkdir(parents=True)
    for d in (pkg, pkg / "sub"):
        (d / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "sub" / "model.py").write_text(dedent("""\
        from .helper import h
        from . import other
        from ..up import u
        """), encoding="utf-8")
    (pkg / "sub" / "helper.py").write_text("import pandas as pd\nh = pd.read_csv\n",
                                           encoding="utf-8")
    (pkg / "sub" / "other.py").write_text("x = open\n", encoding="utf-8")
    (pkg / "up.py").write_text("import subprocess\nu = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    got, scanned = static_findings([pkg / "sub" / "model.py"], S["static_check"]["forbidden"],
                                   follow=["xprel"], trusted=[])
    # `from . import other` imports the package too, so its __init__.py is scanned.
    assert {p.name for p in scanned} == {"model.py", "helper.py", "other.py", "up.py",
                                         "__init__.py"}
    assert got == ["helper.py:2: read_csv", "other.py:1: open", "up.py:1: subprocess"]
