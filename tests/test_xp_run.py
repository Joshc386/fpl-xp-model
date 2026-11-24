"""The xP backtest end to end on the synthetic season, with stub models built against the
hand-off interfaces: the holdout switch, an honest stub, the planted leak as the model, a
component stub, a hand-off violation, determinism and the report's headings."""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest
from backtest.elo_check import load_settings
from backtest.elo_data import HarnessError
from backtest.run_backtest import run
from backtest.xp_inputs import last5_per_fixture, read
from backtest.xp_leakage import peeking_baselines
from backtest.xp_report import render
from backtest.xp_settings import HoldoutError, Predictors

import synth
from elo_check_runs import INFO
from elo_check_synth import BASE_CFG
from xp_synth import synth_reads

SEASON = synth.SEASON
HEADINGS = ["**Verdict:**", "**Code under test:**", "**Headline results:**",
            "**Calibration:**", "**Ranking:**", "**Component checks:**", "**Leakage:**",
            "**Early season:**", "**Weakest areas:**", "**Concerns:**",
            "**Open questions and blockers:**"]


def settings(**over: object) -> dict:
    s = copy.deepcopy(load_settings()["xp_backtest"])
    s["seasons"] = [{"id": SEASON, "target_gameweeks": [4, 9]}]
    s["holdout_seasons"] = ["2026-2027"]
    s["perturbation"]["cases"] = [{"season": SEASON, "as_of": 6}]
    s["static_check"]["paths"] = []
    s["gate"]["calibration_min_count"] = 5
    s["weakest"]["min_rows"] = 3
    s["metrics"]["top_n"] = 3
    return s | over


def stub_xp(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
    """An honest stub of `fpl.xp.xp` (the contract's Combine row): one row per player per
    Premier League fixture of his club in the next 3 gameweeks, with `team_id`, `match_id`,
    `gw`, `xp_appear`, `xp_cards` and `xp_total` (points per fixture over his last 3 fixture
    gameweeks, plus a little)."""
    t = read(season, as_of_gw, mode)
    rate = last5_per_fixture(t, as_of_gw, "prem", 3)
    fx = t["fact_fixture"]
    fx = fx[(fx.tournament == "prem") & fx.gw.between(as_of_gw + 1, as_of_gw + 3)]
    players = list(zip(t["dim_player"].player_id, t["dim_player"].team_id, strict=True))
    return pd.DataFrame([
        {"player_id": p, "team_id": club, "match_id": m.match_id, "gw": m.gw,
         "xp_appear": 1.5, "xp_cards": -0.1, "xp_total": rate.get(p, 0.0) + 0.1 * (p % 3)}
        for m in fx.itertuples() for p, club in players
        if club in (m.home_team_id, m.away_team_id)])


def stub_minutes(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
    """An honest stub of the minutes component: p_60 per player per fixture, from his FPL
    minutes in the as-of gameweek."""
    t = read(season, as_of_gw, mode)
    fx = t["fact_fixture"]
    fx = fx[(fx.gw > as_of_gw) & (fx.tournament == "prem")]
    gw = t["fact_player_gw"]
    last = gw[gw.gw == as_of_gw].set_index("player_id").minutes
    rows = [{"player_id": p, "match_id": m.match_id, "gw": m.gw,
             "p_60": min(1.0, 0.1 + float(last.get(p, 0)) / 100)}
            for m in fx.itertuples()
            for p, club in zip(t["dim_player"].player_id, t["dim_player"].team_id, strict=True)
            if club in (m.home_team_id, m.away_team_id)]
    return pd.DataFrame(rows)


def peeking_xp(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
    """The planted leak dressed as a model: next gameweek's actual points."""
    s = settings()
    out = peeking_baselines(season, as_of_gw, mode, s=s, prem="prem")
    return out[["player_id", "team_id", "gw"]].assign(
        match_id="any", xp_appear=0.0, xp_cards=0.0, xp_total=out.last5)


def timing(s: dict, finals: dict) -> pd.DataFrame:
    """A stand-in for the git-history check: GW5's snapshot (predicting GW6) is late."""
    return pd.DataFrame({"season": SEASON, "snapshot": [4, 5, 6], "target": [5, 6, 7],
                         "late": [False, True, False], "refers_to": [5, 7, 7],
                         "refers_share": [1.0, 0.9, 1.0], "note": ""})


def do_run(src: Path, preds: Predictors, s: dict | None = None, **kw: object) -> dict:
    with synth_reads(src) as reads:
        out = run(s or settings(), preds, BASE_CFG, src, point=reads.point, timing=timing,
                  **kw)
    out["_calls"] = reads.calls
    return out


@pytest.fixture(scope="module")
def src(synth_upstream: tuple[Path, dict]) -> Path:
    return synth_upstream[0] / "data"


@pytest.fixture(scope="module")
def honest(src: Path) -> dict:
    return do_run(src, Predictors(model=stub_xp, components={"minutes": stub_minutes}))


def test_a_holdout_season_is_refused_without_the_switch_before_any_read(src: Path) -> None:
    s = settings(seasons=[{"id": "2026-2027", "target_gameweeks": [2, 10]}])
    with synth_reads(src) as reads, pytest.raises(HoldoutError, match="holdout"):
        run(s, Predictors(), BASE_CFG, src, point=reads.point, timing=timing)
    assert reads.calls == []


def test_a_holdout_perturbation_case_is_refused_before_any_read(src: Path) -> None:
    s = settings()
    s["perturbation"]["cases"] = [{"season": "2026-2027", "as_of": 3}]
    refused = pytest.raises(HoldoutError, match="2026-2027")
    with synth_reads(src) as reads, refused, \
            mock.patch("backtest.run_backtest.copy_upstream") as copied:
        run(s, Predictors(), BASE_CFG, src, point=reads.point, timing=timing)
    assert reads.calls == [] and not copied.called


def test_with_the_switch_a_holdout_season_needs_the_pre_deadline_view(src: Path) -> None:
    s = settings(holdout_seasons=[SEASON])
    with synth_reads(src) as reads, pytest.raises(RuntimeError, match="pre-deadline view"):
        run(s, Predictors(), BASE_CFG, src, point=reads.point, timing=timing,
            allow_holdout=True)
    assert reads.calls, "the switch lets the run read"


def test_every_predictor_is_scored_on_identical_rows_in_backtest_mode(honest: dict) -> None:
    df = honest["scored"]
    assert sorted(df.gw.unique()) == list(range(4, 10))
    assert df[["ep_next", "last5", "ppg", "model"]].notna().all().all()
    assert {c[2] for c in honest["_calls"]} == {"backtest"}
    assert {c[1] for c in honest["_calls"]} <= set(range(3, 10))  # as-of g-1, final 9
    head = honest["summary"]["all"]["headline"].set_index("predictor")
    assert head.n.nunique() == 1 and head.loc["model", "n"] == len(df)


def test_the_honest_run_passes_leakage_and_catches_the_planted_leak(honest: dict) -> None:
    met = honest["leakage_met"]
    assert met == {"perturbation": True, "planted_leak_caught": True, "copy_reached": True,
                   "static": True, "refit": True}
    case = honest["leakage"]["cases"][0]
    assert set(case["functions"]) == {"baselines", "model", "minutes", "planted_leak"}


def test_the_planted_leak_as_the_model_fails_the_leakage_criteria(src: Path) -> None:
    out = do_run(src, Predictors(model=peeking_xp))
    assert out["leakage_met"]["perturbation"] is False
    assert out["gate"]["model"]["passed"] is False


def test_components_are_diagnosed_when_built_and_reported_missing_otherwise(honest: dict
                                                                            ) -> None:
    comp = honest["components"]
    summary = comp["minutes"]["summary"].set_index("group")
    assert summary.loc["all", "n"] == summary.loc["Europe", "n"] + summary.loc["rest", "n"]
    assert summary.loc["all", "n"] > 0
    assert set(comp) == {"minutes"}


def test_a_model_missing_a_player_stops_the_run(src: Path) -> None:
    def short(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
        return stub_xp(season, as_of_gw, mode).query("player_id != 1")

    with pytest.raises(HarnessError, match="no prediction"):
        do_run(src, Predictors(model=short))


def test_the_evaluation_set_depends_on_no_predictor(honest: dict, src: Path) -> None:
    def contrarian(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
        out = stub_xp(season, as_of_gw, mode)
        return out.assign(xp_total=(out.player_id % 2) * 0.0 - out.xp_total)

    keys = ["season", "gw", "player_id"]
    base = do_run(src, Predictors())["scored"][keys]
    other = do_run(src, Predictors(model=contrarian))["scored"][keys]
    assert honest["scored"][keys].equals(base) and other.equals(base)
    assert honest["counts"].equals(do_run(src, Predictors())["counts"])


def test_the_report_has_every_heading_and_is_deterministic(honest: dict, src: Path) -> None:
    text = render(honest, INFO)
    positions = [text.index(h) for h in HEADINGS]
    assert positions == sorted(positions)
    assert "dry run" in text and "late snapshots" in text
    assert "late snapshot" in checklist_line(text, "Features for gameweek g")
    assert "minus 90 minutes" in text and "Controls:" in text
    assert "2025/26 and 2026/27" in text.split("**Open questions and blockers:**")[1]
    again = do_run(src, Predictors(model=stub_xp, components={"minutes": stub_minutes}))
    assert render(again, INFO) == text


def test_baselines_only_scores_the_three_baselines_and_dry_runs_the_gate(src: Path) -> None:
    out = do_run(src, Predictors())
    assert "model" not in out["scored"].columns
    assert set(out["gate"]) == {"last5", "ppg"}
    assert out["components"] == {}
    text = render(out, INFO)
    assert "**Verdict:** none, harness build" in text


def checklist_line(text: str, item: str) -> str:
    return next(ln for ln in text.splitlines() if ln.startswith(f"| {item}"))


def test_the_synthetic_reads_reach_a_module_holding_the_loader_by_name(
        src: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real component imports load_as_of by name: inside the swap it reads the synthetic
    season, not the real checkout."""
    import types

    from fpl.features import load_as_of
    holder = types.ModuleType("fpl.models.planted_component")
    holder.load_as_of = load_as_of
    monkeypatch.setitem(sys.modules, holder.__name__, holder)
    with synth_reads(src) as reads:
        holder.load_as_of(SEASON, 3, "backtest")
    assert reads.calls == [(SEASON, 3, "backtest")]
    assert holder.load_as_of is load_as_of


def reads_the_real_data(src: Path) -> object:
    """A model that adds the next gameweek's points, read straight from the real data."""
    def predict(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
        out = stub_xp(season, as_of_gw, mode)
        path = src / season / "By Gameweek" / f"GW{as_of_gw + 1}" / "player_gameweek_stats.csv"
        pts = pd.read_csv(path).set_index("id").event_points
        return out.assign(xp_total=out.xp_total + out.player_id.map(pts).fillna(0.0))
    return predict


def starts_a_process(season: str, as_of_gw: int, mode: str) -> pd.DataFrame:
    """A model that starts a process (which could read anything)."""
    subprocess.run([sys.executable, "-c", "pass"], check=True)
    return stub_xp(season, as_of_gw, mode)


def test_a_model_reading_the_real_data_fails_a_full_run(src: Path) -> None:
    out = do_run(src, Predictors(model=reads_the_real_data(src)))
    assert out["leakage_met"]["perturbation"] is False
    got = out["leakage"]["cases"][0]["functions"]["model"]
    assert got["changed"] is None and "outside the scratch copy" in got["error"]
    assert out["leakage"]["cases"][0]["functions"]["baselines"]["changed"] == 0


def test_a_model_starting_a_process_fails_a_full_run(src: Path) -> None:
    out = do_run(src, Predictors(model=starts_a_process))
    assert out["leakage_met"]["perturbation"] is False
    assert "subprocess.Popen" in out["leakage"]["cases"][0]["functions"]["model"]["error"]
