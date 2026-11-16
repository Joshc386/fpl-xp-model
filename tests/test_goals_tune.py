"""The goals-prior tuner: its log-loss, grid and guards, and a known-output synthetic curve.

The real run (2025/26 GW6-38, 33 as-of reads, about 70 s) is too slow for the suite; its curve
is in docs/decisions.md ("model - goals-prior tuner and units guard").
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable

import numpy as np
import pandas as pd
import pytest

from elo_tables import PREM, Fixture, season_read
from fpl.models import elo, goals_tune
from fpl.models.elo import model_config, pipeline_config
from fpl.models.goals_tune import grid_settings, log_loss_curve, poisson_log_loss, tune

SEASON = "2025-2026"
# A double round robin of six clubs (codes 41-46), three matches a gameweek, scores drawn once
# from Poisson with a seeded generator and fixed here: (gw, home, away, home goals, away goals).
SCORES = [
    (1, 1, 6, 5, 0), (1, 5, 2, 2, 1), (1, 3, 4, 0, 0),
    (2, 5, 1, 1, 0), (2, 6, 4, 1, 1), (2, 3, 2, 3, 1),
    (3, 1, 4, 5, 1), (3, 3, 5, 4, 1), (3, 6, 2, 1, 2),
    (4, 3, 1, 3, 2), (4, 4, 2, 5, 1), (4, 6, 5, 1, 2),
    (5, 1, 2, 3, 0), (5, 6, 3, 0, 5), (5, 4, 5, 3, 1),
    (6, 6, 1, 1, 2), (6, 2, 5, 0, 1), (6, 4, 3, 2, 2),
    (7, 1, 5, 1, 0), (7, 4, 6, 3, 2), (7, 2, 3, 0, 0),
    (8, 4, 1, 1, 3), (8, 5, 3, 2, 1), (8, 2, 6, 3, 1),
    (9, 1, 3, 3, 0), (9, 2, 4, 1, 1), (9, 5, 6, 3, 0),
    (10, 2, 1, 2, 0), (10, 3, 6, 4, 1), (10, 5, 4, 1, 1),
]
CODES = {i: 40 + i for i in range(1, 7)}
UPSTREAM = {1: 1700.0, 2: 1640.0, 3: 1590.0, 4: 1540.0, 5: 1490.0, 6: 1430.0}


def as_of_tables(season: str, as_of: int, mode: str) -> dict[str, pd.DataFrame]:
    """The synthetic season as `load_as_of` would return it: later fixtures schedule only."""
    assert (season, mode) == (SEASON, "backtest")
    fixtures: list[Fixture] = [
        (gw, h, a, hg, ag, UPSTREAM[h], UPSTREAM[a]) if gw <= as_of
        else (gw, h, a, None, None, None, None) for gw, h, a, hg, ag in SCORES]
    return season_read(season, as_of, CODES, fixtures).tables


def small_config(grid: list[float] | None = None) -> dict:
    """The real config, with the synthetic season's minimum pool, gameweeks and grid."""
    cfg = model_config()
    cfg["goals_model"]["min_matches"] = 6
    cfg["goals_model"]["tuning"] |= {"scored_gameweeks": [4, 10], "gap_points": 100,
                                     "shared_sd_grid": grid or [0.3, 0.175, 0.1]}
    return cfg


@pytest.fixture
def loads(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int, str]]:
    """Every `load_as_of` call the model makes, answered from the synthetic season."""
    calls: list[tuple[str, int, str]] = []

    def fake(season: str, as_of: int, mode: str) -> dict[str, pd.DataFrame]:
        calls.append((season, as_of, mode))
        return as_of_tables(season, as_of, mode)

    monkeypatch.setattr(elo, "load_as_of", fake)
    return calls


def test_poisson_log_loss_against_hand_values() -> None:
    # -ln P(y): lam - y ln lam + ln y!. 1.0; 1.5 - 2 ln 1.5 + ln 2; 0.5 - 3 ln 0.5 + ln 6.
    out = poisson_log_loss(np.array([0.0, 2.0, 3.0]), np.array([1.0, 1.5, 0.5]))
    assert out == pytest.approx([1.0, 1.382216965, 4.371201011], abs=1e-9)


def test_the_grid_sets_both_priors_from_one_sd_and_adds_the_no_prior_row() -> None:
    cfg = model_config()
    tuning = cfg["goals_model"]["tuning"]
    grid = grid_settings(cfg)  # through GoalsSettings.from_config, so the units guard passes
    assert list(grid) == [math.inf, *tuning["shared_sd_grid"]]
    assert grid[math.inf].precision.tolist() == [0.0, 0.0, 0.0]
    for sd in tuning["shared_sd_grid"]:
        assert grid[sd].prior_sd_home == sd
        assert grid[sd].prior_sd_gap == pytest.approx(sd / tuning["gap_points"], rel=1e-12)
        assert grid[sd].prior_sd_gap < cfg["goals_model"]["prior_sd_gap_max"]
        assert grid[sd].min_matches == cfg["goals_model"]["min_matches"]


def test_a_grid_value_the_units_guard_rejects_stops_the_tuner() -> None:
    cfg = model_config()
    cfg["goals_model"]["tuning"]["gap_points"] = 1  # 0.4 per rating point
    with pytest.raises(ValueError, match="prior_sd_gap is per rating point"):
        grid_settings(cfg)


Frames = tuple[pd.DataFrame, pd.DataFrame]
Change = Callable[[pd.DataFrame, pd.DataFrame], Frames]


def curve_inputs() -> Frames:
    """Predictions at shared sd 0.2 and inf for one match's two teams, and their goals."""
    actual = pd.DataFrame({"match_id": ["m1", "m1"], "team_id": [1, 2], "goals": [0.0, 2.0]})
    preds = pd.DataFrame({"match_id": ["m1"] * 4, "team_id": [1, 2, 1, 2],
                          "lambda_for": [1.0, 1.5, 2.0, 2.0],
                          "shared_sd": [0.2, 0.2, math.inf, math.inf]})
    return preds, actual


def test_the_curve_is_the_mean_log_loss_per_shared_sd() -> None:
    curve = log_loss_curve(*curve_inputs()).set_index("shared_sd")
    # 0.2: (1.0 + 1.382217) / 2. inf: (2 + 2 - 2 ln 2 + ln 2) / 2 = (4 - ln 2) / 2.
    assert curve.log_loss.to_dict() == pytest.approx({0.2: 1.191108483, math.inf: 1.653426410})
    assert curve.team_fixtures.tolist() == [2, 2]


@pytest.mark.parametrize(("change", "match"), [
    (lambda p, a: (p.iloc[1:], a), "no prediction"),
    (lambda p, a: (p, a.iloc[1:]), "no result"),
    (lambda p, a: (pd.concat([p, p.iloc[:1]]), a), "more than one prediction"),
])
def test_the_curve_refuses_unmatched_or_duplicated_rows(change: Change, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        log_loss_curve(*change(*curve_inputs()))


def test_known_output_on_the_synthetic_season(loads: list[tuple[str, int, str]]) -> None:
    # Expected values from a separate loop over goals_from_history with its own join and
    # log-loss (2026-11-15). GW g is scored from the read as of g-1; results from as-of 10.
    curve = tune(SEASON, list(range(4, 11)), small_config(), PREM).set_index("shared_sd")
    assert curve.log_loss.to_dict() == pytest.approx(
        {math.inf: 1.552859012, 0.3: 1.511886684, 0.175: 1.520959909, 0.1: 1.545679019},
        abs=1e-9)
    assert (curve.team_fixtures == 42).all() and curve.index.tolist() == [math.inf, 0.3, 0.175,
                                                                          0.1]
    assert curve.prior_sd_gap.tolist() == pytest.approx([math.inf, 0.003, 0.00175, 0.001])
    assert loads == [(SEASON, g, "backtest") for g in range(3, 10)] + [(SEASON, 10, "backtest")]


@pytest.mark.parametrize(("grid", "priors", "best", "verdict"), [
    ([0.3, 0.175, 0.1], {}, "0.3", "DIFFERS"),
    ([0.175, 0.1], {}, "0.175", "matches"),
    # The best gap prior but not the best home prior, and the other way round: each DIFFERS.
    # The config's priors don't enter the curve, since every row sets both of its own.
    ([0.175, 0.1], {"prior_sd_home": 0.2}, "0.175", "DIFFERS"),
    ([0.175, 0.1], {"prior_sd_gap": 0.002}, "0.175", "DIFFERS"),
], ids=["best-differs", "best-matches", "home-differs", "gap-differs"])
def test_main_logs_the_curve_the_minimum_and_the_config_check(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    loads: list[tuple[str, int, str]], grid: list[float], priors: dict[str, float], best: str,
    verdict: str,
) -> None:
    cfg = small_config(grid)
    cfg["goals_model"] |= priors
    monkeypatch.setattr(goals_tune, "model_config", lambda: cfg)
    with caplog.at_level(logging.INFO, logger="fpl.models.goals_tune"):
        goals_tune.main()
    assert f"Minimum: shared sd {best} " in caplog.text and f"({verdict})" in caplog.text
    assert "1.55286" in caplog.text and "42 team-fixtures" in caplog.text
    assert {season for season, _, _ in loads} == {SEASON}


def test_the_logged_minimum_skips_the_no_prior_row_when_it_scores_best(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    loads: list[tuple[str, int, str]],
) -> None:
    # A prior sd of 0.01 pins both coefficients near zero, so the no-prior reference row has the
    # lowest log-loss; the minimum reported against the config must still be a grid value.
    curves: list[pd.DataFrame] = []

    def recorded_tune(*args: object) -> pd.DataFrame:
        curves.append(tune(*args))
        return curves[-1]

    monkeypatch.setattr(goals_tune, "model_config", lambda: small_config([0.01]))
    monkeypatch.setattr(goals_tune, "tune", recorded_tune)
    with caplog.at_level(logging.INFO, logger="fpl.models.goals_tune"):
        goals_tune.main()
    assert curves[0].set_index("shared_sd").log_loss.idxmin() == math.inf
    assert "Minimum: shared sd 0.01 " in caplog.text and "(DIFFERS)" in caplog.text


def test_main_refuses_a_duplicate_grid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    # The curve is keyed by sd, so a duplicate would otherwise become one row without a word.
    cfg = model_config()
    cfg["goals_model"]["tuning"]["shared_sd_grid"] = [0.2, 0.175, 0.2]
    monkeypatch.setattr(goals_tune, "model_config", lambda: cfg)
    monkeypatch.setattr(elo, "load_as_of", lambda *a: pytest.fail("must not load"))
    with pytest.raises(ValueError, match=r"shared_sd_grid has duplicate values \[0\.2\]"):
        goals_tune.main()


def holdout_config(season: str, start: str) -> dict:
    cfg = model_config()
    cfg["goals_model"]["tuning"]["season"], cfg["elo"]["start_season"] = season, start
    return cfg


@pytest.mark.parametrize(("season", "start", "match"), [
    ("2026-2027", "2025-2026", "never tune on the holdout"),  # not the run's first season
    ("2026-2027", "2026-2027", "never tune on the holdout"),  # start moved: still the holdout
    ("2099-2100", "2025-2026", "must be in"),
])
def test_main_refuses_any_season_but_the_runs_first(
    monkeypatch: pytest.MonkeyPatch, season: str, start: str, match: str
) -> None:
    monkeypatch.setattr(goals_tune, "model_config", lambda: holdout_config(season, start))
    monkeypatch.setattr(elo, "load_as_of", lambda *a: pytest.fail("must not load"))
    with pytest.raises(ValueError, match=match):
        goals_tune.main()


def test_main_refuses_a_later_season_that_is_neither_newest_nor_current(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    # 2026-2027 is a middle season and not the current one, so only "the run's first" refuses it.
    def three_seasons() -> dict:
        cfg = pipeline_config()
        cfg["seasons"] = [*cfg["seasons"], {"id": "2027-2028", "gameweeks": 38}]
        return cfg | {"current_season": "2027-2028"}

    monkeypatch.setattr(goals_tune, "pipeline_config", three_seasons)
    monkeypatch.setattr(goals_tune, "model_config",
                        lambda: holdout_config("2026-2027", "2025-2026"))
    monkeypatch.setattr(elo, "load_as_of", lambda *a: pytest.fail("must not load"))
    with pytest.raises(ValueError, match="never tune on the holdout"):
        goals_tune.main()


@pytest.mark.parametrize("gws", [[0, 38], [6, 39], [10, 6]])
def test_main_refuses_scored_gameweeks_outside_the_season(
    monkeypatch: pytest.MonkeyPatch, gws: list[int]
) -> None:
    cfg = model_config()
    cfg["goals_model"]["tuning"]["scored_gameweeks"] = gws
    monkeypatch.setattr(goals_tune, "model_config", lambda: cfg)
    monkeypatch.setattr(elo, "load_as_of", lambda *a: pytest.fail("must not load"))
    with pytest.raises(ValueError, match="scored_gameweeks"):
        goals_tune.main()
