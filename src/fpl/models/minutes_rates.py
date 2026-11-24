"""The minutes component's per-player rates (brief section 6.1), used by `models/minutes.py`.

From his last `minutes.windows` Premier League gameweeks with a club fixture
(`features.recent_minutes`), each player gets a recency-weighted start rate, starts / fixtures,
and four rates from single-fixture gameweeks, shrunk toward the season-to-date position
average: P(60 | start), minutes given a start, the bench-appearance rate and minutes given a
bench appearance. A player with no history takes the position average for all five.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from fpl.features import recent_minutes

HISTORY_COUNTS = ["minutes", "starts", "fixtures"]
# The four rates shrunk toward a position prior: (numerator count, denominator count) from
# `gameweek_counts`. The start rate, starts / fixtures, is not shrunk (brief 6.1).
RATES = {
    "p60_given_start": ("start_60", "start_obs"),
    "minutes_given_start": ("start_minutes", "start_obs"),
    "bench_rate": ("bench_apps", "bench_obs"),
    "minutes_given_bench": ("bench_minutes", "bench_apps"),
}
RATE_COUNTS = sorted({c for pair in RATES.values() for c in pair})
# The position priors: `RATES` and the start rate, which a player with no history takes.
PRIOR_RATES = {"start_rate": ("starts", "fixtures"), **RATES}


class MinutesError(ValueError):
    """The minutes component cannot be computed from the read or the settings."""


def gameweek_weights(windows: Sequence[int], weights: Sequence[float]) -> np.ndarray:
    """The weight of the player's r-th most recent gameweek (r = 0 first), for r < max(windows).

    A gameweek weighs the share of the window weights whose window holds it, so the most
    recent gameweek, in every window, weighs 1. A rate weighted this way equals
    sum_N w_N * count_N / sum_N w_N * base_N over the window totals of `recent_minutes`.
    Windows must be strictly increasing positive integers, with one positive weight each.
    """
    wins, ws = [int(n) for n in windows], [float(w) for w in weights]
    if not wins or len(wins) != len(ws):
        raise MinutesError(f"need one weight per window, got windows {wins} and weights {ws}")
    if wins[0] < 1 or any(b <= a for a, b in zip(wins, wins[1:], strict=False)):
        raise MinutesError(f"windows must be strictly increasing positive integers, got {wins}")
    if min(ws) <= 0:
        raise MinutesError(f"window weights must be positive, got {ws}")
    recency = np.arange(wins[-1])
    held = np.array(wins)[None, :] > recency[:, None]
    return (held * np.array(ws)).sum(axis=1) / sum(ws)


def gameweek_history(tables: dict[str, pd.DataFrame], as_of_gw: int, depth: int,
                     prem_tag: str) -> pd.DataFrame:
    """Each player's last `depth` gameweeks with a club fixture, one row each, most recent first.

    The rows come from `recent_minutes` window totals for windows 1..`depth`: the gameweek at
    recency r (0 = most recent) is window r + 1 minus window r. So the windows follow its rules
    exactly (the club of each gameweek, blank gameweeks skipped, a double gameweek one row
    with `fixtures` 2). Returns `player_id`, `recency`, `minutes`, `starts`, `fixtures`;
    a player has no row for a recency beyond his history.
    """
    columns = ["player_id", "recency", *HISTORY_COUNTS]
    totals = recent_minutes(tables, as_of_gw, list(range(1, depth + 1)), prem_tag)
    if totals.empty:   # no players at all (as-of 0)
        return pd.DataFrame({c: pd.Series(dtype="int64") for c in columns})
    wide = totals.pivot(index="player_id", columns="window", values=HISTORY_COUNTS)
    per_gw = {c: wide[c].diff(axis=1).fillna(wide[c]).astype("int64") for c in HISTORY_COUNTS}
    long = pd.concat(
        {c: f.rename(columns=lambda n: n - 1).stack() for c, f in per_gw.items()}, axis=1
    ).rename_axis(["player_id", "recency"]).reset_index()
    long = long[long.fixtures > 0]
    return long[columns].sort_values(["player_id", "recency"], ignore_index=True)


def gameweek_counts(history: pd.DataFrame, long_minutes: int) -> pd.DataFrame:
    """`history` with the per-gameweek counts behind each rate (see `RATES`).

    `starts` and `fixtures` give the start rate in every gameweek, a double included. The
    other counts come from single-fixture gameweeks only, where FPL's gameweek minutes are the
    match's minutes: a start (`start_obs`) that reached `long_minutes` (`start_60`) and its
    minutes, and a match not started (`bench_obs`) with a bench appearance (`bench_apps`) and
    its minutes. In a double gameweek FPL gives one minutes total for two matches, so which
    start reached 60, or whether minutes came from a start or the bench, is unknown.
    """
    single = history.fixtures == 1
    start = single & (history.starts == 1)
    bench = single & (history.starts == 0)
    played = history.minutes > 0
    return history.assign(
        start_obs=start.astype("int64"),
        start_60=(start & (history.minutes >= long_minutes)).astype("int64"),
        start_minutes=history.minutes.where(start, 0),
        bench_obs=bench.astype("int64"),
        bench_apps=(bench & played).astype("int64"),
        bench_minutes=history.minutes.where(bench, 0),
    )


def _ratio(num: pd.Series | float, den: pd.Series | float,
           fallback: pd.Series | float) -> np.ndarray:
    """num / den, or `fallback` where den is 0."""
    num, den = np.asarray(num, dtype="float64"), np.asarray(den, dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / den, fallback)


def position_priors(counts: pd.DataFrame, positions: pd.Series) -> pd.DataFrame:
    """The season-to-date rate of each of `PRIOR_RATES` by position, one row per position.

    Every gameweek row in `counts` of a player with a position in `positions` (player_id ->
    position) counts once, unweighted. A position with no observation for a rate takes the
    league's (all positions pooled); with none in the league either, the rate is 0, which only
    happens when no player has the event it conditions on, so it multiplies a zero.
    """
    cols = ["starts", "fixtures", *RATE_COUNTS]
    known = counts[counts.player_id.isin(positions.index)]
    by_pos = known.groupby(known.player_id.map(positions))[cols].sum()
    by_pos = by_pos.reindex(sorted(set(positions)), fill_value=0)
    league = known[cols].sum()
    out = pd.DataFrame(index=by_pos.index)
    for rate, (num, den) in PRIOR_RATES.items():
        overall = float(_ratio(league[num], league[den], 0.0))
        out[rate] = _ratio(by_pos[num], by_pos[den], overall)
    return out.rename_axis("position")


def player_rates(counts: pd.DataFrame, positions: pd.Series, weights: np.ndarray,
                 priors: pd.DataFrame, prior_strength: float) -> pd.DataFrame:
    """Each player's recency-weighted rates, one row per player in `positions`.

    The gameweek at recency r weighs `weights[r]` (0 beyond them). `start_rate` is weighted
    starts over weighted fixtures, so a double gameweek counts as two matches. Each of `RATES`
    is shrunk toward the player's position prior with strength k = `prior_strength`:
    (weighted numerator + k * prior) / (weighted denominator + k). A player with no fixture
    in the windows (a new arrival) takes his position's prior for every rate, the start rate
    included (brief "Horizon and aggregation"; decided 2026-11-24).
    """
    w = np.zeros(len(counts))
    inside = counts.recency.to_numpy() < len(weights)
    w[inside] = weights[counts.recency.to_numpy()[inside]]
    cols = ["starts", "fixtures", *RATE_COUNTS]
    weighted = counts[cols].mul(w, axis=0).groupby(counts.player_id).sum()
    weighted = weighted.reindex(positions.index, fill_value=0.0)
    prior = priors.loc[positions.to_numpy()].set_axis(positions.index)
    k = prior_strength
    out = pd.DataFrame(
        {"start_rate": _ratio(weighted.starts, weighted.fixtures, prior.start_rate)},
        index=positions.index.rename("player_id"))
    for rate, (num, den) in RATES.items():
        out[rate] = (weighted[num] + k * prior[rate]) / (weighted[den] + k)
    return out
