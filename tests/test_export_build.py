"""build_outputs and publish on small synthetic reads: contents, atomic writes, no publish on
a failed check."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from export_outputs import BOUNDS, RUN
from export_tables import AS_OF, PREM, SEASON, tables
from fpl.export import build_outputs, publish
from fpl.models.elo import SeasonRead
from fpl.output_checks import check_outputs
from fpl.output_schema import output_columns
from fpl.validate import ValidationError

SCORES = {"m1": (2, 0, 1600.0, 1500.0), "m2": (1, 1, None, None), "m3": (0, 1, None, None),
          "m4": (3, 1, None, None)}
COMMIT = "ac8be9caa3bce7aa6c2b73d5a33a9f5c0b2f0e41"
MCFG = {
    "model_version": "9.9.9-test", "max_horizon": 5,
    "elo": {"k": 20, "home_advantage": 50, "margin_power": 0.5, "scale": 400},
    "goals_model": {"pool_seasons": 2, "min_matches": 3, "newton_tol": 1e-10,
                    "newton_max_iter": 50},
}
PCFG = {"premier_league_tag": PREM, "validation": {"now_cost_m": BOUNDS["now_cost_m"]},
        "position_map": dict(zip(["Goalkeeper", "Defender", "Midfielder", "Forward"],
                                 BOUNDS["positions"], strict=True)),
        "output_validation": {k: BOUNDS[k] for k in ("elo_rating_range", "lambda_max",
                                                     "tolerance")}}


def history() -> list[SeasonRead]:
    t = tables()
    fx = t["fact_fixture"].copy()
    for mid, (hg, ag, he, ae) in SCORES.items():
        row = fx.match_id == mid
        fx.loc[row, ["home_goals", "away_goals"]] = [hg, ag]
        fx.loc[row, ["home_upstream_elo", "away_upstream_elo"]] = [he, ae]
    t["fact_fixture"] = fx
    return [SeasonRead(SEASON, AS_OF, t)]


def deadlines() -> pd.Series:
    return pd.Series(pd.date_range("2026-09-01T12:00:00Z", periods=8, freq="D"),
                     index=range(1, 9))


def built() -> tuple[dict[str, pd.DataFrame], object]:
    return build_outputs(history(), deadlines(), RUN, COMMIT, next_gw=4, mcfg=MCFG, pcfg=PCFG)


def test_build_outputs_makes_the_four_files_with_contract_columns() -> None:
    out, _ = built()
    assert list(out) == ["players", "fixture_difficulty", "elo_ratings", "meta"]
    for name, df in out.items():
        assert list(df.columns) == output_columns(name)


def test_build_outputs_passes_its_own_checks() -> None:
    out, ctx = built()
    check_outputs(out, ctx)


def test_fixture_difficulty_holds_the_horizon_fixture_once_per_team() -> None:
    fd = built()[0]["fixture_difficulty"]
    assert sorted(zip(fd.team_id, fd.team, fd.match_id, fd.gw, fd.opponent_id, fd.opponent,
                      fd.home, strict=True)) == [
        (1, "ALP", "m6", 4, 2, "BET", True), (2, "BET", "m6", 4, 1, "ALP", False)]


def test_elo_ratings_have_two_rows_per_finished_premier_league_match() -> None:
    elo = built()[0]["elo_ratings"]
    assert len(elo) == 8 and set(elo.match_id) == {"m1", "m2", "m3", "m4"}


def test_a_postponed_fixture_before_the_as_of_gameweek_is_not_an_elo_match() -> None:
    reads = history()
    fx = reads[0].tables["fact_fixture"]
    row = fx.match_id == "m2"          # gameweek 2, still unplayed at as-of 3
    fx.loc[row, ["finished", "stats_complete"]] = False
    fx.loc[row, ["home_goals", "away_goals"]] = pd.NA
    out, ctx = build_outputs(reads, deadlines(), RUN, COMMIT, next_gw=4, mcfg=MCFG, pcfg=PCFG)
    check_outputs(out, ctx)
    assert set(out["elo_ratings"].match_id) == {"m1", "m3", "m4"}


def test_meta_row_values() -> None:
    m = built()[0]["meta"].iloc[0]
    assert (m.run_utc, m.upstream_commit, m.current_gw, m.next_gw) == (
        "2026-09-03T20:00:00Z", COMMIT, 3, 4)
    assert (m.next_deadline_utc, m.model_version, m.max_horizon, m.status) == (
        "2026-09-04T12:00:00Z", "9.9.9-test", 5, "ok")
    assert pd.isna(m.backtest_mae_model) and pd.isna(m.backtest_mae_ep_next)


def test_publish_writes_four_csvs_that_read_back_equal(tmp_path: Path) -> None:
    out, ctx = built()
    paths = publish(out, ctx, tmp_path / "out")
    assert sorted(p.name for p in paths.values()) == [
        "elo_ratings.csv", "fixture_difficulty.csv", "meta.csv", "players.csv"]
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == sorted(
        p.name for p in paths.values())
    players = pd.read_csv(paths["players"])
    assert list(players.columns) == output_columns("players")
    assert players.loc[players.player_id == 10, "price_m"].item() == 5.6
    meta = pd.read_csv(paths["meta"], keep_default_na=False)
    assert meta.run_utc.item() == "2026-09-03T20:00:00Z" and meta.backtest_mae_model.item() == ""


def test_a_failed_check_writes_nothing_and_leaves_existing_files(tmp_path: Path) -> None:
    out, ctx = built()
    out["fixture_difficulty"].loc[0, "lambda_for"] = -1.0
    target = tmp_path / "out"
    target.mkdir()
    (target / "players.csv").write_text("old", encoding="utf-8")
    with pytest.raises(ValidationError):
        publish(out, ctx, target)
    assert [p.name for p in target.iterdir()] == ["players.csv"]
    assert (target / "players.csv").read_text(encoding="utf-8") == "old"


def test_a_failed_check_does_not_even_create_the_directory(tmp_path: Path) -> None:
    out, ctx = built()
    out["meta"].loc[0, "status"] = "bad"
    with pytest.raises(ValidationError):
        publish(out, ctx, tmp_path / "never")
    assert not (tmp_path / "never").exists()


def test_a_rename_that_fails_removes_the_temporary_files_and_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, ctx = built()
    real_replace, calls = os.replace, []

    def flaky(src: Path, dst: Path) -> None:
        calls.append(dst)
        if len(calls) == 3:
            raise PermissionError("held open")
        real_replace(src, dst)

    monkeypatch.setattr("fpl.export.os.replace", flaky)
    with pytest.raises(PermissionError):
        publish(out, ctx, tmp_path)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["fixture_difficulty.csv", "players.csv"]    # the two renamed before it failed
    assert not any(n.endswith(".tmp") for n in names)
