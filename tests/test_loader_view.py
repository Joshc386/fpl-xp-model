"""The backtest read's `dim_player` comes from the pre-deadline view (synthetic season)."""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

import fpl.features
import synth
from fpl.deadline_view import COPY_VIEW_DIR, ViewError
from fpl.features import load_as_of, use_data_copy
from fpl.schema import column_names

SEASON = synth.SEASON
FIX = r"python -m fpl\.pre_deadline"
BUMP = 100  # tenths added to every price in the altered views


@pytest.fixture
def setup(synth_upstream: tuple[Path, dict], tmp_path: Path) -> tuple[Path, dict]:
    """A private copy of the synthetic view, and a config that reads it."""
    root, cfg = synth_upstream
    view_dir = tmp_path / "pre_deadline"
    shutil.copytree(root / "pre_deadline", view_dir)
    return view_dir, {**cfg, "paths": {**cfg["paths"], "pre_deadline_dir": str(view_dir)}}


def edit_view(view_dir: Path, change: Callable[[pd.DataFrame], pd.DataFrame]) -> None:
    path = view_dir / f"{SEASON}.parquet"
    df = pd.read_parquet(path)
    change(df).to_parquet(path, index=False)


def bump(df: pd.DataFrame) -> pd.DataFrame:
    return df.assign(price_tenths=df.price_tenths + BUMP, status="d")


def player(tables: dict, pid: int) -> pd.Series:
    dim = tables["dim_player"]
    return dim[dim.player_id == pid].iloc[0]


@pytest.mark.parametrize("as_of", [1, 2, 20, 36, 37])
def test_a_backtest_read_takes_dim_player_from_the_next_gameweeks_view(
    setup: tuple[Path, dict], synth_load: Callable[[int, str], dict], as_of: int
) -> None:
    view_dir, cfg = setup
    edit_view(view_dir, bump)
    snapshot = synth_load(as_of, "backtest")["dim_player"]
    got = load_as_of(SEASON, as_of, "backtest", cfg=cfg)["dim_player"]
    assert list(got.columns) == column_names("dim_player")
    assert (got.price_tenths.to_numpy() == snapshot.price_tenths.to_numpy() + BUMP).all()
    assert (got.status == "d").all() and (snapshot.status != "d").all()


def test_the_view_row_used_is_the_one_of_gameweek_as_of_plus_one(
    setup: tuple[Path, dict]
) -> None:
    view_dir, cfg = setup
    # Each gameweek's view gets its own price, so the read shows which gameweek it took.
    edit_view(view_dir, lambda df: df.assign(price_tenths=df.gw * 10))
    for as_of in (1, 12, 37):
        got = load_as_of(SEASON, as_of, "backtest", cfg=cfg)["dim_player"]
        assert (got.price_tenths == (as_of + 1) * 10).all()


def test_as_of_0_stays_empty_and_as_of_38_keeps_the_snapshots_players(
    setup: tuple[Path, dict], synth_load: Callable[[int, str], dict]
) -> None:
    view_dir, cfg = setup
    edit_view(view_dir, bump)
    assert load_as_of(SEASON, 0, "backtest", cfg=cfg)["dim_player"].empty
    got = load_as_of(SEASON, 38, "backtest", cfg=cfg)["dim_player"]
    pd.testing.assert_frame_equal(got, synth_load(38, "backtest")["dim_player"])


@pytest.mark.parametrize("as_of", [0, 1, 20, 38])
def test_the_edges_need_no_view_when_the_view_isnt_used(
    setup: tuple[Path, dict], as_of: int
) -> None:
    view_dir, cfg = setup
    if as_of in (0, 38):
        shutil.rmtree(view_dir)  # neither as-of 0 nor 38 reads the view
        assert len(load_as_of(SEASON, as_of, "backtest", cfg=cfg)["fact_fixture"]) > 0
    else:
        shutil.rmtree(view_dir)
        with pytest.raises(ViewError, match=FIX):
            load_as_of(SEASON, as_of, "backtest", cfg=cfg)


@pytest.mark.parametrize("as_of", [1, 20, 37, 38])
def test_live_mode_never_reads_the_view(
    setup: tuple[Path, dict], synth_load: Callable[[int, str], dict], as_of: int
) -> None:
    view_dir, cfg = setup
    edit_view(view_dir, bump)
    shutil.rmtree(view_dir)
    got = load_as_of(SEASON, as_of, "live", cfg=cfg)
    pd.testing.assert_frame_equal(got["dim_player"], synth_load(as_of, "live")["dim_player"])


# ---- the refusals -------------------------------------------------------------------------


def test_a_missing_view_refuses_and_does_not_fall_back_to_the_snapshot(
    setup: tuple[Path, dict]
) -> None:
    view_dir, cfg = setup
    shutil.rmtree(view_dir)
    with pytest.raises(ViewError, match=FIX):
        load_as_of(SEASON, 20, "backtest", cfg=cfg)


def test_a_view_without_the_gameweek_refuses(setup: tuple[Path, dict]) -> None:
    view_dir, cfg = setup
    edit_view(view_dir, lambda df: df[df.gw != 21])
    with pytest.raises(ViewError, match=rf"lacks GW21.*{FIX}"):
        load_as_of(SEASON, 20, "backtest", cfg=cfg)
    assert len(load_as_of(SEASON, 19, "backtest", cfg=cfg)["dim_player"]) == 8  # others read


def test_a_view_built_from_another_checkout_commit_refuses(setup: tuple[Path, dict]) -> None:
    view_dir, cfg = setup
    record = view_dir / f"{SEASON}.json"
    info = json.loads(record.read_text(encoding="utf-8"))
    record.write_text(json.dumps({**info, "checkout_commit": "c" * 40}), encoding="utf-8")
    with pytest.raises(ViewError, match=rf"stale.*{FIX}"):
        load_as_of(SEASON, 20, "backtest", cfg=cfg)


def test_a_view_row_from_a_commit_after_the_deadline_refuses(setup: tuple[Path, dict]) -> None:
    view_dir, cfg = setup
    late = f"{synth.FIRST_KICKOFF + pd.Timedelta(days=7 * 21):%Y-%m-%dT%H:%M:%SZ}"  # GW21's kickoff
    edit_view(view_dir, lambda df: df.assign(
        commit_utc=df.commit_utc.where(df.gw != 21, late)))
    with pytest.raises(ViewError, match="after the deadline"):
        load_as_of(SEASON, 20, "backtest", cfg=cfg)


# ---- the players of the read --------------------------------------------------------------


def test_players_missing_from_the_view_are_dropped_counted_and_keep_their_facts(
    setup: tuple[Path, dict], synth_load: Callable[[int, str], dict],
    caplog: pytest.LogCaptureFixture,
) -> None:
    view_dir, cfg = setup
    edit_view(view_dir, lambda df: df[~((df.gw == 21) & df.player_id.isin([3, 5]))])
    with caplog.at_level(logging.INFO, logger="fpl.features"):
        got = load_as_of(SEASON, 20, "backtest", cfg=cfg)
    assert sorted(got["dim_player"].player_id) == [1, 2, 4, 6, 7, 8]
    snap = synth_load(20, "backtest")
    pd.testing.assert_frame_equal(got["fact_player_gw"], snap["fact_player_gw"])
    pd.testing.assert_frame_equal(got["fact_player_match"], snap["fact_player_match"])
    assert any("2 players dropped" in r.getMessage() for r in caplog.records)


def test_the_view_supplies_the_whole_record_club_included(setup: tuple[Path, dict]) -> None:
    view_dir, cfg = setup
    edit_view(view_dir, lambda df: df.assign(
        team_id=df.team_id.where(df.gw != 21, 4), pen_order=7, ep_next=9.5, selected_pct=88.0,
        web_name="Z", news="from the view"))
    p = player(load_as_of(SEASON, 20, "backtest", cfg=cfg), 1)
    assert (p.team_id, p.pen_order, p.ep_next, p.selected_pct) == (4, 7, 9.5, 88.0)
    assert (p.web_name, p.news) == ("Z", "from the view")


def test_the_two_modes_differ_in_dim_player_only_where_the_view_does(
    setup: tuple[Path, dict]
) -> None:
    # The view equals the snapshot here, so the modes agree apart from the live overlay; with an
    # altered view, backtest's dim_player is the view and live's still the snapshot plus overlay.
    view_dir, cfg = setup
    back = load_as_of(SEASON, 20, "backtest", cfg=cfg)
    live = load_as_of(SEASON, 20, "live", cfg=cfg)
    for name in back:
        if name != "dim_player":
            pd.testing.assert_frame_equal(back[name], live[name])
    edit_view(view_dir, bump)
    again = load_as_of(SEASON, 20, "backtest", cfg=cfg)
    for name in again:
        if name != "dim_player":
            pd.testing.assert_frame_equal(again[name], live[name])
    assert not again["dim_player"].equals(live["dim_player"])


@pytest.mark.parametrize("offset", [0, -1])
def test_a_view_row_committed_at_the_derived_deadline_exactly_is_refused(
    setup: tuple[Path, dict], offset: int
) -> None:
    # GW21's derived deadline is its first kickoff minus 90 minutes; one second before passes.
    view_dir, cfg = setup
    deadline = synth.FIRST_KICKOFF + pd.Timedelta(days=7 * 21, minutes=-90, seconds=offset)
    stamp = f"{deadline:%Y-%m-%dT%H:%M:%SZ}"
    edit_view(view_dir, lambda df: df.assign(commit_utc=df.commit_utc.where(df.gw != 21, stamp)))
    if offset == 0:
        with pytest.raises(ViewError, match="at or after the deadline"):
            load_as_of(SEASON, 20, "backtest", cfg=cfg)
    else:
        assert len(load_as_of(SEASON, 20, "backtest", cfg=cfg)["dim_player"]) == 8


def test_a_view_row_committed_at_its_own_earlier_deadline_is_refused(
    setup: tuple[Path, dict]
) -> None:
    view_dir, cfg = setup
    edit_view(view_dir, lambda df: df.assign(
        deadline_utc=df.deadline_utc.where(df.gw != 21, df.commit_utc)))
    with pytest.raises(ViewError, match="at or after the deadline"):
        load_as_of(SEASON, 20, "backtest", cfg=cfg)


# ---- reads inside a data copy ----------------------------------------------------------------


@pytest.fixture
def copy_dir(synth_upstream: tuple[Path, dict], setup: tuple[Path, dict], tmp_path: Path,
             monkeypatch: pytest.MonkeyPatch) -> Path:
    """A data copy holding its own view (a private copy of the synthetic one), with the
    loader's configuration for reads that name none set to the synthetic one."""
    root, cfg = synth_upstream
    dest = tmp_path / "copy" / "data"
    shutil.copytree(root / "data", dest)
    shutil.copytree(root / "pre_deadline", dest / COPY_VIEW_DIR)
    monkeypatch.setattr(fpl.features, "load_config", lambda _path: setup[1])
    return dest


def test_a_read_inside_a_data_copy_takes_the_copys_own_view_not_the_configured_one(
    setup: tuple[Path, dict], copy_dir: Path
) -> None:
    view_dir, cfg = setup
    edit_view(copy_dir / COPY_VIEW_DIR, bump)  # only the copy's view is altered
    configured = load_as_of(SEASON, 20, "backtest", cfg=cfg)["dim_player"]
    with use_data_copy(copy_dir):
        inside = load_as_of(SEASON, 20, "backtest")["dim_player"]
    assert (inside.price_tenths.to_numpy() == configured.price_tenths.to_numpy() + BUMP).all()
    assert (inside.status == "d").all() and (configured.status != "d").all()


def test_a_data_copy_with_no_view_refuses_although_the_configured_view_exists(
    copy_dir: Path
) -> None:
    shutil.rmtree(copy_dir / COPY_VIEW_DIR)
    with use_data_copy(copy_dir), pytest.raises(ViewError, match="missing"):
        load_as_of(SEASON, 20, "backtest")


def test_a_call_with_its_own_cfg_inside_a_data_copy_uses_the_configured_view(
    setup: tuple[Path, dict], copy_dir: Path
) -> None:
    view_dir, cfg = setup
    edit_view(copy_dir / COPY_VIEW_DIR, bump)
    outside = load_as_of(SEASON, 20, "backtest", cfg=cfg)["dim_player"]
    with use_data_copy(copy_dir):
        explicit = load_as_of(SEASON, 20, "backtest", cfg=cfg)["dim_player"]
    pd.testing.assert_frame_equal(explicit, outside)
    assert not (explicit.status == "d").any()
