"""The outside-source Elo check end to end on the seeded synthetic world (no real data)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from backtest.beyondelo_check import run, run_check
from backtest.beyondelo_data import CheckError
from backtest.beyondelo_fit import FitError

from beyondelo_check_synth import S1, S2, settings, world

INFO = {"date": "2026-11-17", "commit": "abc"}


def test_every_window_is_counted_and_complete() -> None:
    r = run_check(settings(), world())
    assert r["counts"] == {
        "fit": {"matches": 60, "finished_result": 60, "our_rating": 60,
                "beyondelo_rating": 60, "complete": 60},
        f"{S1} GW13-18": {"matches": 30, "finished_result": 30, "our_rating": 30,
                          "beyondelo_rating": 30, "complete": 30},
        f"{S2} GW3-10": {"matches": 40, "finished_result": 40, "our_rating": 40,
                         "beyondelo_rating": 40, "complete": 40},
    }
    assert r["verdict"]["n"] == 70


def test_the_scored_2026_27_window_stays_pinned_when_the_data_runs_past_it() -> None:
    # The synthetic S2 has ratings, beyondELO rows and finished results up to GW12.
    w = world()
    assert w.fixtures[S2].gw.max() == 12 and w.ours[w.ours.season == S2].gw.max() == 12
    r = run_check(settings(), w)
    s2 = r["scored"][r["scored"].season == S2]
    assert sorted(set(s2.gw)) == list(range(3, 11)) and len(s2) == 40
    assert set(r["fit_table"].gw) == set(range(1, 13)) and set(r["fit_table"].season) == {S1}


def test_an_affine_copy_of_our_ratings_scores_the_same_as_ours() -> None:
    r = run_check(settings(), world(theirs=lambda o, t, rng: 0.37 * o + 912.0))
    sc = r["scored"]
    assert np.abs(sc.nll_ours - sc.nll_beyondelo).max() < 1e-12
    v = r["verdict"]
    assert abs(v["mean"]) < 1e-12 and not v["worse_than_beyondelo"]
    assert r["fits"]["beyondelo"].slope == pytest.approx(r["fits"]["ours"].slope / 0.37, rel=1e-9)


def test_pure_noise_ratings_do_no_better_than_the_baseline() -> None:
    def noise(truth: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        return rng.normal(1500.0, 120.0, len(truth))

    v = run_check(settings(), world(ours=noise))["verdict"]
    assert v["ours"] >= v["baseline"]
    assert v["not_below_baseline"] and v["poor"]


def test_informative_ratings_beat_the_baseline() -> None:
    v = run_check(settings(), world())["verdict"]
    assert v["ours"] < v["baseline"] and not v["not_below_baseline"]


@pytest.mark.parametrize("side", ["home", "away"])
def test_matches_with_a_promoted_club_on_either_side_are_left_out_of_the_extra_figures(
        side: str) -> None:
    r = run_check(settings(), world(promoted=frozenset({3})))
    sc = r["scored"]
    col = f"{side}_team_id"
    assert ((sc[col] == 3) & sc.promoted).any()
    plays = (sc.home_team_id == 3) | (sc.away_team_id == 3)
    assert (plays & (sc.season == S1)).any()  # promoted is per season: S2 only here
    keep = sc[~(plays & (sc.season == S2))]
    row = r["log_loss"]["without_promoted"].set_index("window").loc["pooled"]
    assert row.n == len(keep) < len(sc)
    assert row.ours == pytest.approx(keep.nll_ours.mean(), abs=1e-15)
    assert row.beyondelo == pytest.approx(keep.nll_beyondelo.mean(), abs=1e-15)
    assert row.baseline == pytest.approx(keep.nll_base.mean(), abs=1e-15)
    assert r["promoted"] == {S1: [], S2: ["Club03"]}
    # The verdict still uses every scored match.
    assert r["verdict"]["n"] == len(sc)


def _drop_ours(w, season: str, gw: int) -> None:
    hit = (w.ours.season == season) & (w.ours.gw == gw)
    w.ours = w.ours.drop(index=w.ours.index[hit][:1])


def _drop_beyondelo(w, season: str, gw: int) -> None:
    b = w.beyondelo[season]
    w.beyondelo[season] = b.drop(index=b.index[b.gw == gw][:1])


def _unfinish(w, season: str, gw: int) -> None:
    f = w.fixtures[season]
    i = f.index[f.gw == gw][:1]
    f.loc[i, "finished"] = False
    f.loc[i, ["home_goals", "away_goals"]] = pd.NA


@pytest.mark.parametrize(("kind", "spoil"), [("our_rating", _drop_ours),
                                             ("beyondelo_rating", _drop_beyondelo),
                                             ("finished_result", _unfinish)])
@pytest.mark.parametrize(("season", "gw", "window"), [(S1, 5, "fit"),
                                                      (S1, 14, f"{S1} GW13-18"),
                                                      (S2, 10, f"{S2} GW3-10")])
def test_a_missing_partner_stops_the_run_with_no_report(tmp_path: Path, kind: str, spoil,
                                                        season: str, gw: int,
                                                        window: str) -> None:
    w = world()
    spoil(w, season, gw)
    with pytest.raises(CheckError) as exc:
        run(settings(), w, INFO, tmp_path)
    msg = str(exc.value)
    assert window in msg and f"no {kind.replace('_', ' ')}" in msg.lower()
    assert "matches" in msg
    assert list(tmp_path.iterdir()) == []


def test_a_gap_outside_the_windows_doesnt_stop_the_run() -> None:
    w = world()
    _drop_ours(w, S2, 12)  # after the pinned window
    _drop_beyondelo(w, S2, 1)  # before it
    assert run_check(settings(), w)["verdict"]["n"] == 70


def test_a_fit_that_doesnt_converge_stops_the_run_with_no_report(tmp_path: Path) -> None:
    s = settings()
    s["beyondelo_check"]["max_iterations"] = 1
    with pytest.raises(FitError, match="the ours fit on the fit window: Newton-Raphson"):
        run(s, world(), INFO, tmp_path)
    assert list(tmp_path.iterdir()) == []
