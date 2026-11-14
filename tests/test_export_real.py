"""The export on the real upstream checkout (skipped when it is not there).

Runs pinned to 2026-11-13 12:00Z (next gameweek 11, as-of 10) and to just before the GW10
deadline (next 10, as-of 9). The loader reads are memoised, and counted. Nothing writes outside
pytest's temporary directories.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fpl import export
from fpl.features import live_deadlines, load_as_of
from fpl.ingest import ROOT, load_config, upstream_data_dir
from fpl.models import elo
from fpl.models.elo import elo_ratings
from fpl.models.team_goals import elo_goals
from fpl.output_schema import output_columns

CFG = load_config(ROOT / "config" / "pipeline.yaml")
SEASON = CFG["current_season"]
DATA = upstream_data_dir(CFG) / SEASON
pytestmark = pytest.mark.skipif(not (DATA / "By Gameweek" / "GW10").exists(),
                                reason="no upstream checkout")
RUN = datetime.fromisoformat("2026-11-13T12:00:00+00:00")
FILES = ["players", "fixture_difficulty", "elo_ratings", "meta"]


@pytest.fixture(scope="module")
def real(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict]:
    """Two exports (as-of 10 and 9) and the loader calls they made."""
    cache: dict[tuple[str, int, str], dict] = {}
    calls: list[tuple[str, int, str]] = []

    def load(season: str, as_of: int, mode: str) -> dict:
        calls.append((season, as_of, mode))
        if (season, as_of, mode) not in cache:
            cache[(season, as_of, mode)] = load_as_of(season, as_of, mode)
        return cache[(season, as_of, mode)]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(elo, "load_as_of", load)
        out10 = export.run_export(tmp_path_factory.mktemp("gw10"), RUN)
        export_calls = list(calls)
        before_gw10 = live_deadlines(SEASON).loc[10] - pd.Timedelta(minutes=1)
        out9 = export.run_export(tmp_path_factory.mktemp("gw9"), before_gw10.to_pydatetime())
        yield {"out10": out10, "out9": out9, "calls": export_calls, "load": load,
               "public": (elo_ratings(SEASON, 10, "live"), elo_goals(SEASON, 10, "live"))}


def read(paths: dict[str, Path], name: str) -> pd.DataFrame:
    return pd.read_csv(paths[name], keep_default_na=False, na_values=[""])


def test_export_reads_each_season_once(real: dict) -> None:
    assert real["calls"] == [("2025-2026", 38, "backtest"), (SEASON, 10, "live")]


def test_files_have_the_contract_columns(real: dict) -> None:
    for name in FILES:
        assert list(read(real["out10"], name).columns) == output_columns(name)


def test_elo_and_difficulty_equal_the_public_functions(real: dict) -> None:
    ratings, goals = real["public"]
    pd.testing.assert_frame_equal(
        read(real["out10"], "elo_ratings"), ratings, check_dtype=False, rtol=1e-12)
    pd.testing.assert_frame_equal(
        read(real["out10"], "fixture_difficulty").drop(columns=["team", "opponent"]), goals,
        check_dtype=False, rtol=1e-12)


def test_meta_and_row_counts_on_the_latest_snapshot(real: dict) -> None:
    meta = read(real["out10"], "meta").iloc[0]
    assert (meta.current_gw, meta.next_gw, meta.max_horizon) == (10, 11, 5)
    assert meta.model_version == "0.1.0-elo" and meta.status == "ok"
    assert pd.isna(meta.backtest_mae_model) and len(meta.upstream_commit) == 40
    dim = real["load"](SEASON, 10, "live")["dim_player"]
    assert len(read(real["out10"], "players")) == len(dim)


def prem(fx: pd.DataFrame) -> pd.DataFrame:
    return fx[fx.tournament == CFG["premier_league_tag"]]


def test_row_counts_follow_from_the_fixtures(real: dict) -> None:
    now = prem(real["load"](SEASON, 10, "live")["fact_fixture"])
    last = prem(real["load"]("2025-2026", 38, "backtest")["fact_fixture"])
    horizon = now[now.gw.between(11, 15)]
    assert len(read(real["out10"], "fixture_difficulty")) == 2 * len(horizon)
    played = int(last.finished.sum()) + int((now.finished & (now.gw <= 10)).sum())
    assert len(read(real["out10"], "elo_ratings")) == 2 * played


def test_fixture_difficulty_names_are_dim_team_short_names(real: dict) -> None:
    teams = real["load"](SEASON, 10, "live")["dim_team"].set_index("team_id").short_name
    fd = read(real["out10"], "fixture_difficulty")
    assert (fd.team == fd.team_id.map(teams)).all()
    assert (fd.opponent == fd.opponent_id.map(teams)).all()


def test_players_reconcile_with_fpls_own_season_totals(real: dict) -> None:
    ours = read(real["out10"], "players").set_index("player_id")
    fpl = pd.read_csv(DATA / "By Gameweek" / "GW10" / "playerstats.csv").set_index("id")
    fpl = fpl.reindex(ours.index)
    for col in ("total_points", "minutes", "starts"):
        assert (ours[col] == fpl[col]).all()
    assert ((ours.ppg - fpl.points_per_game).abs() <= 0.05 + 1e-9).all()   # FPL rounds to 0.1
    assert (ours.pen_taker == (fpl.penalties_order == 1)).all()
    assert np.allclose(ours.dc90 * ours.minutes / 90, fpl.defensive_contribution)
    assert not ours.isna().drop(columns=["chance_next", "news"]).any().any()
    dim = real["load"](SEASON, 10, "live")
    short = dim["dim_team"].set_index("team_id").short_name
    assert (ours.team == dim["dim_player"].set_index("player_id").team_id.map(short)
            .reindex(ours.index)).all()


def test_current_state_columns_equal_the_latest_master_row(real: dict) -> None:
    ours = read(real["out10"], "players").set_index("player_id")
    master = pd.read_csv(DATA / "playerstats.csv").sort_values("gw")
    latest = master.drop_duplicates("id", keep="last").set_index("id").reindex(ours.index)
    assert (ours.price_m == latest.now_cost).all()
    assert (ours.net_transfers_gw == latest.transfers_in_event - latest.transfers_out_event).all()
    assert np.allclose(ours.price_change_gw, latest.cost_change_event / 10)
    assert np.allclose(ours.price_change_start, latest.cost_change_start / 10)


def test_run_pinned_before_the_gw10_deadline_uses_gameweek_9(real: dict) -> None:
    meta = read(real["out9"], "meta").iloc[0]
    assert (meta.current_gw, meta.next_gw) == (9, 10)
    fd = read(real["out9"], "fixture_difficulty")
    assert fd.gw.min() == 10 and fd.gw.max() == 14
    elo_rows = read(real["out9"], "elo_ratings")
    assert elo_rows[elo_rows.season == SEASON].gw.max() == 9
    ours = read(real["out9"], "players").set_index("player_id")
    fpl = pd.read_csv(DATA / "By Gameweek" / "GW9" / "playerstats.csv").set_index("id")
    assert (ours.total_points == fpl.total_points.reindex(ours.index)).all()
