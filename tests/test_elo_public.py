"""The public functions on the synthetic upstream: reads, modes and the point-in-time prefix."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import pytest

import synth
from elo_tables import two_seasons
from fpl.models import elo
from fpl.models.elo import MissingSeedError, elo_ratings, load_history
from fpl.models.team_goals import elo_goals


@pytest.fixture
def on_synth(monkeypatch: pytest.MonkeyPatch, synth_load: Callable[[int, str], dict]) -> None:
    """Point the Elo component's loader at the synthetic 2025-2026 season."""
    monkeypatch.setattr(elo, "load_as_of", lambda season, as_of, mode: synth_load(as_of, mode))


def prem_matches_up_to(as_of: int) -> list[dict]:
    return [m for m in synth.schedule() if m["tournament"] == "prem" and m["gw"] <= as_of]


@pytest.mark.usefixtures("on_synth")
def test_both_modes_give_the_same_output() -> None:
    pd.testing.assert_frame_equal(elo_ratings(synth.SEASON, 20, "backtest"),
                                  elo_ratings(synth.SEASON, 20, "live"))
    pd.testing.assert_frame_equal(elo_goals(synth.SEASON, 20, "backtest"),
                                  elo_goals(synth.SEASON, 20, "live"))


@pytest.mark.usefixtures("on_synth")
def test_ratings_up_to_g_are_the_same_at_as_of_g_and_as_of_38() -> None:
    full = elo_ratings(synth.SEASON, 38, "backtest")
    for as_of in (6, 8):  # as-of reads the suite already caches; GW7 is a double
        part = elo_ratings(synth.SEASON, as_of, "backtest")
        pd.testing.assert_frame_equal(part, full[full.gw <= as_of].reset_index(drop=True))


@pytest.mark.usefixtures("on_synth")
def test_rows_are_the_league_matches_only_and_seeds_are_gw1_values() -> None:
    out = elo_ratings(synth.SEASON, 19, "backtest")
    assert set(out.match_id) == {m["id"] for m in prem_matches_up_to(19)}  # no cup-10, cup-late
    first = out.groupby("team_id").elo_before.first()
    assert first.to_dict() == {t: 1501.0 + 10 * t for t in synth.TEAM_CODE}  # 1500 + 10t + gw1


@pytest.mark.usefixtures("on_synth")
def test_fixture_difficulty_covers_the_next_five_gameweeks() -> None:
    out = elo_goals(synth.SEASON, 20, "backtest")
    assert sorted(set(out.gw)) == [21, 22, 23, 24, 25] and len(out) == 2 * 2 * 5
    assert (out.lambda_for > 0).all() and out.p_cs.between(0, 1).all()


@pytest.mark.usefixtures("on_synth")
def test_as_of_0_has_no_seed_and_raises() -> None:
    with pytest.raises(MissingSeedError, match="as-of 0"):
        elo_ratings(synth.SEASON, 0, "backtest")
    with pytest.raises(MissingSeedError):
        elo_goals(synth.SEASON, 0, "backtest")


def test_earlier_seasons_are_read_in_full_in_backtest_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int, str]] = []
    tables = {read.season: read.tables for read in two_seasons()}

    def fake(season: str, as_of: int, mode: str) -> dict:
        calls.append((season, as_of, mode))
        return tables[season]

    monkeypatch.setattr(elo, "load_as_of", fake)
    history = load_history("2026-2027", 4, "live")
    assert calls == [("2025-2026", 38, "backtest"), ("2026-2027", 4, "live")]
    assert [(r.season, r.as_of_gw) for r in history] == [("2025-2026", 38), ("2026-2027", 4)]
    calls.clear()
    load_history("2025-2026", 7, "live")
    assert calls == [("2025-2026", 7, "live")]


@pytest.mark.parametrize("season", ["2024-2025", "2030-2031"])
def test_a_season_outside_the_run_is_rejected(season: str) -> None:
    with pytest.raises(ValueError, match="not in the Elo run"):
        load_history(season, 5, "backtest")
