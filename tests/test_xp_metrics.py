"""The xP backtest's pure metrics, on small inputs with hand-computed answers."""

from __future__ import annotations

import math

import pandas as pd
import pytest
from backtest.xp_metrics import (
    beats_share,
    bin_table,
    brier,
    errors,
    gameweek_mae,
    spearman_by_position,
    top_n_hits,
)


def frame(**cols: list) -> pd.DataFrame:
    return pd.DataFrame(cols)


def test_errors_gives_count_mae_and_rmse_per_predictor() -> None:
    df = frame(points=[2, 0, 6], a=[1.0, 1.0, 6.0], b=[2.0, 0.0, 2.0])
    out = errors(df, ["a", "b"]).set_index("predictor")
    assert out.loc["a", "n"] == 3
    assert out.loc["a", "mae"] == pytest.approx(2 / 3)
    assert out.loc["a", "rmse"] == pytest.approx(math.sqrt(2 / 3))
    assert out.loc["b", "mae"] == pytest.approx(4 / 3)
    assert out.loc["b", "rmse"] == pytest.approx(math.sqrt(16 / 3))


def test_beats_share_counts_strictly_lower_gameweek_mae() -> None:
    df = frame(gw=[1, 1, 2, 2, 3], points=[0, 2, 0, 2, 1], ep_next=[1, 1, 0, 2, 1],
               m=[0, 2, 1, 1, 1])
    per = gameweek_mae(df, ["ep_next", "m"])
    assert per.loc[1, "ep_next"] == pytest.approx(1.0)
    assert per.loc[1, "m"] == pytest.approx(0.0)
    # GW1 beats, GW2 loses (1 > 0), GW3 ties (not a win): 1 of 3.
    assert beats_share(per, "m", "ep_next") == pytest.approx(1 / 3)


def test_spearman_by_position_per_gameweek_with_undefined_groups_counted() -> None:
    df = frame(gw=[1, 1, 1, 1, 1, 2, 2, 2],
               position=["MID", "MID", "MID", "DEF", "DEF", "MID", "MID", "MID"],
               points=[1, 2, 3, 5, 1, 3, 2, 1],
               p=[0.1, 0.2, 0.3, 4.0, 4.0, 0.1, 0.2, 0.3])
    per, summary = spearman_by_position(df, "p")
    got = per.set_index(["gw", "position"]).rho
    assert got[(1, "MID")] == pytest.approx(1.0)
    assert got[(2, "MID")] == pytest.approx(-1.0)
    assert math.isnan(got[(1, "DEF")])  # constant prediction: undefined
    s = summary.set_index("position")
    assert s.loc["MID", "mean"] == pytest.approx(0.0)
    assert s.loc["MID", "gameweeks"] == 2
    assert s.loc["DEF", "undefined"] == 1


def test_top_n_hits_counts_actual_ties_at_the_cut_and_breaks_predicted_ties_by_id() -> None:
    df = frame(gw=[1] * 5, player_id=[1, 2, 3, 4, 5], points=[10, 8, 8, 1, 0],
               p=[5.0, 1.0, 1.0, 4.0, 0.0])
    # Predicted top 2: ids 1 and 4. Actual top 2 (ties at the cut kept): 1, 2, 3. One hit of 2.
    assert top_n_hits(df, "p", 2).tolist() == [0.5]
    # Predicted top 3: 1, 4, then 2 (tie with 3 broken by id). Actual top 3: 1, 2, 3.
    assert top_n_hits(df, "p", 3).tolist() == [pytest.approx(2 / 3)]


def test_bin_table_lists_every_bin_and_puts_values_below_the_first_edge_in_it() -> None:
    out = bin_table([-0.2, 0.5, 1.0, 9.0], [0, 1, 3, 7], [0, 1, 8])
    assert out.bin.tolist() == ["0-1", "1-8", "8+"]
    assert out["count"].tolist() == [2, 1, 1]
    assert out.mean_pred.iloc[0] == pytest.approx(0.15)
    assert out.mean_actual.iloc[0] == pytest.approx(0.5)
    assert out["diff"].iloc[0] == pytest.approx(0.35)
    empty = bin_table([0.5], [1], [0, 1])
    assert empty["count"].tolist() == [1, 0]
    assert math.isnan(empty.mean_pred.iloc[1])


def test_brier_is_the_mean_squared_probability_error() -> None:
    assert brier([0.0, 1.0, 0.5], [0, 1, 1]) == pytest.approx(0.25 / 3)
    with pytest.raises(ValueError, match="probabilit"):
        brier([1.2], [1])
    assert math.isnan(brier([], []))
