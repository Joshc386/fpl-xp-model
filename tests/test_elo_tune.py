"""The Elo tuning: its metrics against hand values, and a grid that recovers known settings."""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from elo_tables import CODES_A, FIXTURES_A, PREM, SETTINGS, season_read
from fpl.models import elo_tune
from fpl.models.elo import model_config, prepare, run_elo
from fpl.models.elo_tune import (
    end_of_season,
    grid_search,
    kickoff_sides,
    mean_gaps,
    result_log_loss,
    spearman_by_gw,
    target_gameweeks,
    tune,
)

SIDES = pd.DataFrame({
    "gw": [1, 1, 1, 2, 2, 2, 2], "kickoff_utc": ["a", "b", "c", "d", "e", "f", "g"],
    "team_code": [1, 2, 3, 1, 2, 3, 1], "ours": [10.0, 20.0, 30.0, 12.0, 22.0, 28.0, 99.0],
    "after": [11.0, 21.0, 31.0, 13.0, 23.0, 29.0, 100.0],
    "upstream": [11.0, 18.0, 33.0, 30.0, 20.0, 10.0, 0.0],
})


def matching_upstream() -> list:
    """Season A with upstream kickoff Elo equal to our run's elo_before under SETTINGS."""
    run = run_elo([season_read("2025-2026", 3, CODES_A, FIXTURES_A)], SETTINGS, PREM)
    m = run.matches
    return [f[:5] + (h, a) for f, h, a in zip(FIXTURES_A, m.home_elo_before, m.away_elo_before,
                                              strict=True)]


def test_target_gameweeks_expand_inclusive_ranges() -> None:
    assert target_gameweeks([[2, 4], [7, 7]]) == [2, 3, 4, 7]


def test_mean_gaps_are_absolute_and_signed_over_the_target_gameweeks() -> None:
    assert mean_gaps(SIDES, [1]) == pytest.approx(((1 + 2 + 3) / 3, (-1 + 2 - 3) / 3))


def test_spearman_by_gameweek_uses_each_clubs_first_kickoff() -> None:
    out = spearman_by_gw(SIDES).set_index("gw")
    assert out.loc[1].spearman == pytest.approx(1.0) and out.loc[1].clubs == 3
    # GW2: club 1's second kickoff (99 v 0) is ignored; 12, 22, 28 v 30, 20, 10 is reversed.
    assert out.loc[2].spearman == pytest.approx(-1.0) and out.loc[2].clubs == 3


def test_end_of_season_compares_each_clubs_last_rating_after_with_upstream_there() -> None:
    # Last rows: club 1 (100 v 0), club 2 (23 v 20), club 3 (29 v 10). Ranks (3, 1, 2) v
    # (1, 3, 2) give Spearman -1; gaps 100, 3 and 19 average 40.667.
    out = end_of_season(SIDES)
    assert out.clubs == 3 and out.spearman == pytest.approx(-1.0)
    assert out.mean_signed_gap == pytest.approx(122 / 3) and out.mean_gap == pytest.approx(122 / 3)


def test_result_log_loss_against_hand_values() -> None:
    # Home win at E = 0.703385: -ln E = 0.351851. Draw at E = 0.571463:
    # -(ln 0.571463 + ln 0.428537) / 2 = 0.703467. Mean 0.527659.
    matches = pd.DataFrame({"home_elo_before": [1600.0, 1500.0],
                            "away_elo_before": [1500.0, 1500.0],
                            "home_goals": [1, 2], "away_goals": [0, 2]})
    assert result_log_loss(matches, SETTINGS) == pytest.approx(0.527659, abs=1e-6)


def test_the_grid_recovers_the_settings_that_made_the_target() -> None:
    results, seeds = prepare([season_read("2025-2026", 3, CODES_A, matching_upstream())], PREM)
    grid = {"k": [10, 20, 30], "home_advantage": [0, 50], "margin_power": [0, 0.5]}
    out = grid_search(results, seeds, grid, [2, 3], SETTINGS.scale)
    best = out.iloc[0]
    assert (best.k, best.home_advantage, best.margin_power) == (20, 50, 0.5)
    assert best.mean_gap == pytest.approx(0.0, abs=1e-9) and len(out) == 12


def small_config() -> dict:
    cfg = model_config()
    cfg["elo"]["tuning"] |= {"target_gameweeks": [[2, 3]], "check_from_gw": 2,
                             "grid": {"k": [20, 30], "home_advantage": [50], "margin_power": [0.5]}}
    return cfg


def test_tune_reports_spearman_by_gameweek_with_the_moving_flag() -> None:
    history = [season_read("2025-2026", 3, CODES_A, matching_upstream())]
    grid, by_gw, eos = tune(history, small_config(), PREM)
    assert grid.iloc[0].k == 20 and by_gw.target.tolist() == [False, True, True]
    assert eos.clubs == 4
    assert len(kickoff_sides(run_elo(history, SETTINGS, PREM).matches)) == 12


def test_main_tunes_the_start_season_and_logs_the_report(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    read = season_read("2025-2026", 38, CODES_A, matching_upstream())
    calls: list[tuple[str, int, str]] = []

    def fake(season: str, as_of: int, mode: str) -> dict:
        calls.append((season, as_of, mode))
        return read.tables

    monkeypatch.setattr(elo_tune, "load_as_of", fake)
    monkeypatch.setattr(elo_tune, "model_config", small_config)
    with caplog.at_level(logging.INFO, logger="fpl.models.elo_tune"):
        elo_tune.main()
    assert calls == [("2025-2026", 38, "backtest")]
    assert "Best: k=20" in caplog.text and "End of season" in caplog.text


@pytest.mark.parametrize(("season", "start", "match"), [
    ("2026-2027", "2025-2026", "never tune on the holdout"),  # after the run's first season
    ("2026-2027", "2026-2027", "never tune on the holdout"),  # start moved: still the newest
    ("2099-2100", "2025-2026", "must be in"),
])
def test_main_refuses_to_tune_after_the_runs_first_season(
    monkeypatch: pytest.MonkeyPatch, season: str, start: str, match: str
) -> None:
    def holdout() -> dict:
        cfg = model_config()
        cfg["elo"]["tuning"]["season"], cfg["elo"]["start_season"] = season, start
        return cfg

    monkeypatch.setattr(elo_tune, "model_config", holdout)
    monkeypatch.setattr(elo_tune, "load_as_of", lambda *a: pytest.fail("must not load"))
    with pytest.raises(ValueError, match=match):
        elo_tune.main()
