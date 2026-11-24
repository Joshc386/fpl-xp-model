"""`baselines` on the synthetic season, against values worked out from its formulas.

GW5 is a blank for clubs 2 and 4, GW7 a double for clubs 1 and 2 (tests/synth.py).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from backtest.elo_check import load_settings
from backtest.xp_inputs import baselines

import synth
from xp_synth import synth_reads

S = load_settings()["xp_backtest"]


def fixtures(club: int, gw: int) -> int:
    return sum(club in (m["home"], m["away"]) for m in synth.schedule()
               if m["gw"] == gw and m["tournament"] == "prem")


def points(p: int, gw: int) -> int:
    played = [synth.minutes(p, gw)] * fixtures(synth.club(p, gw), gw)
    return sum(played) // 30 + gw % 3


def expected_last5(p: int, as_of: int) -> float:
    gws = [g for g in range(as_of, 0, -1) if fixtures(synth.club(p, g), g) > 0][:5]
    return sum(points(p, g) for g in gws) / sum(fixtures(synth.club(p, g), g) for g in gws)


def expected_ppg(p: int, as_of: int) -> float:
    gws = range(1, as_of + 1)
    apps = sum(fixtures(synth.club(p, g), g) for g in gws if synth.minutes(p, g) > 0)
    return sum(points(p, g) for g in gws) / apps if apps else 0.0


@pytest.fixture(scope="module")
def frames(synth_upstream: tuple[Path, dict]) -> dict[int, pd.DataFrame]:
    with synth_reads(synth_upstream[0] / "data") as reads:
        out = {a: baselines(synth.SEASON, a, "backtest", s=S, prem="prem").set_index("player_id")
               for a in (4, 6)}
    assert {c[1] for c in reads.calls} == {4, 6} and {c[2] for c in reads.calls} == {"backtest"}
    return out


def test_a_blank_target_gameweek_gives_zero_last5_and_ppg(frames: dict) -> None:
    f = frames[4]
    assert (f.gw == 5).all()
    for p in synth.PLAYER_CLUB:
        n = fixtures(synth.club(p, 4), 5)
        assert f.loc[p, "fixtures"] == n
        assert f.loc[p, "last5"] == pytest.approx(expected_last5(p, 4) * n)
        assert f.loc[p, "ppg"] == pytest.approx(expected_ppg(p, 4) * n)
        assert f.loc[p, "ep_next"] == pytest.approx(4 + p / 10)  # FPL's figure, as published
    assert f.loc[[3, 4, 7, 8], "last5"].eq(0).all()


def test_a_double_target_gameweek_doubles_the_per_fixture_baselines(frames: dict) -> None:
    f = frames[6]
    for p in (1, 3):  # clubs 1 and 2 play twice in GW7
        assert f.loc[p, "fixtures"] == 2
        assert f.loc[p, "last5"] == pytest.approx(2 * expected_last5(p, 6))
        assert f.loc[p, "ppg"] == pytest.approx(2 * expected_ppg(p, 6))
    assert f.loc[5, "fixtures"] == 1


def test_the_frame_carries_the_start_rule_and_the_p60_baseline(frames: dict) -> None:
    f = frames[6]
    # Starts are 60+ minute fixtures (synth): a player with minutes 90/60/75 in one of his
    # club's last 3 matches started.
    for p in synth.PLAYER_CLUB:
        recent = [g for g in range(6, 0, -1) if fixtures(synth.club(p, g), g) > 0][:3]
        assert f.loc[p, "started"] == any(synth.minutes(p, g) >= 60 for g in recent)
    assert f.p60_base.between(0, 1).all()
    assert not f.ambiguous.any()
