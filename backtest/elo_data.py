"""The Elo check's data layer: skip handling and joins of model output with actual results.

Every input here is a frame from the two public Elo functions or from `load_as_of`; nothing
reads files and nothing calls model internals.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

GOALS_COLUMNS = ["team_id", "match_id", "gw", "opponent_id", "home", "lambda_for",
                 "lambda_against", "p_cs"]
RATINGS_COLUMNS = ["team_id", "match_id", "season", "gw", "kickoff_utc", "elo_before",
                   "elo_after"]
ModelFn = Callable[[str, int, str], pd.DataFrame]


class HarnessError(RuntimeError):
    """Model output doesn't match its hand-off interface or the evaluation set."""


class UnexpectedReadError(RuntimeError):
    """A read raised where the contract says it shouldn't: a finding, so the run stops."""


@dataclass(frozen=True)
class Skip:
    """One read that raised by design and was skipped."""

    function: str
    season: str
    as_of: int
    error: str
    message: str


@dataclass
class SkipLog:
    """Calls model functions, skipping and counting only the reads that raise by design.

    `expected` maps function name -> season -> as-of -> the exception class that read must
    raise.
    """

    expected: dict[str, dict[str, dict[int, type[Exception]]]]
    skips: list[Skip] = field(default_factory=list)
    unraised: list[tuple[str, str, int]] = field(default_factory=list)

    def call(self, name: str, fn: ModelFn, season: str, as_of: int,
             mode: str) -> pd.DataFrame | None:
        """`fn(season, as_of, mode)`, or None for an expected skip; raises on anything else."""
        want = self.expected.get(name, {}).get(season, {}).get(as_of)
        try:
            out = fn(season, as_of, mode)
        except Exception as exc:
            if want is not None and type(exc) is want:
                self.skips.append(Skip(name, season, as_of, type(exc).__name__, str(exc)))
                log.info("skipped %s(%s, %d): %s", name, season, as_of, type(exc).__name__)
                return None
            raise UnexpectedReadError(
                f"{name}({season} as-of {as_of}) raised {type(exc).__name__}: {exc}") from exc
        if want is not None:
            self.unraised.append((name, season, as_of))
            log.warning("%s(%s, %d) was expected to raise %s and didn't", name, season, as_of,
                        want.__name__)
        return out


def _check_columns(df: pd.DataFrame, need: list[str], name: str) -> None:
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise HarnessError(f"{name} output lacks hand-off columns {missing}")


def match_results(fx: pd.DataFrame, prem_tag: str) -> pd.DataFrame:
    """Finished Premier League fixtures of a `fact_fixture` table, one row per match."""
    done = fx[(fx.tournament == prem_tag) & fx.finished]
    if done[["home_goals", "away_goals"]].isna().any().any():
        raise HarnessError("a finished Premier League fixture has no score")
    return done.reset_index(drop=True)


def team_results(fx: pd.DataFrame, prem_tag: str) -> pd.DataFrame:
    """One row per team per finished Premier League fixture, with goals for and against."""
    done = match_results(fx, prem_tag)
    keys = ["season", "match_id", "gw", "kickoff_utc"]
    sides = []
    for side, other, home in (("home", "away", True), ("away", "home", False)):
        sides.append(pd.DataFrame({
            **{k: done[k] for k in keys}, "team_id": done[f"{side}_team_id"].astype("int64"),
            "opponent_id": done[f"{other}_team_id"].astype("int64"), "home": home,
            "goals_for": done[f"{side}_goals"].astype("int64"),
            "goals_against": done[f"{other}_goals"].astype("int64"),
        }))
    return pd.concat(sides, ignore_index=True)


def _gameweek_keys(fx: pd.DataFrame, gw: int, prem_tag: str) -> set[tuple[str, bool]]:
    league = fx[(fx.tournament == prem_tag) & (fx.gw == gw)]
    return {(m, h) for m in league.match_id for h in (True, False)}


def score_gameweek(preds: pd.DataFrame, results: pd.DataFrame, fx: pd.DataFrame, gw: int,
                   prem_tag: str) -> pd.DataFrame:
    """GW `gw`'s predictions with the actual goals for and against, one row per team-fixture.

    Raises `HarnessError` if a column is missing, if the predictions don't cover exactly
    GW `gw`'s Premier League fixtures (two team-fixtures each), or if a club disagrees.
    """
    _check_columns(preds, GOALS_COLUMNS, "elo_goals")
    p = preds[preds.gw == gw]
    have = set(zip(p.match_id, p.home.astype(bool), strict=True))
    want = _gameweek_keys(fx, gw, prem_tag)
    if have != want or len(p) != len(want):
        raise HarnessError(f"GW{gw}: predictions cover {len(have)} team-fixtures, the schedule "
                           f"{len(want)} ({len(want - have)} missing, {len(have - want)} extra)")
    out = p.merge(results.drop(columns="gw"), on=["match_id", "home"], how="left",
                  suffixes=("", "_actual"), validate="one_to_one")
    if out.goals_for.isna().any():
        raise HarnessError(f"GW{gw}: a predicted fixture has no finished result")
    if (out.team_id != out.team_id_actual).any():
        raise HarnessError(f"GW{gw}: a prediction's club differs from the fixture's")
    out = out.assign(clean_sheet=out.goals_against == 0)
    return out.drop(columns=["team_id_actual", "opponent_id_actual"])


def rating_pairs(ratings: pd.DataFrame, fx: pd.DataFrame, gw: int, prem_tag: str) -> pd.DataFrame:
    """Our `elo_before` at every GW `gw` team-kickoff, paired with upstream Elo at it.

    Raises `HarnessError` if the ratings don't cover every GW `gw` team-kickoff exactly once.
    Pairs whose upstream Elo is null are dropped (none are expected in 2025/26).
    """
    _check_columns(ratings, RATINGS_COLUMNS, "elo_ratings")
    r = ratings[ratings.gw == gw]
    league = fx[(fx.tournament == prem_tag) & (fx.gw == gw)]
    m = r.merge(league[["match_id", "home_team_id", "away_team_id", "home_upstream_elo",
                        "away_upstream_elo"]], on="match_id", how="inner", validate="many_to_one")
    home = m.team_id == m.home_team_id
    sides_ok = (home | (m.team_id == m.away_team_id)).all()
    if len(m) != len(r) or len(r) != 2 * len(league) or not sides_ok:
        raise HarnessError(f"GW{gw}: {len(r)} rating rows for {len(league)} fixtures")
    m["upstream_elo"] = m.home_upstream_elo.where(home, m.away_upstream_elo)
    keep = ["season", "gw", "match_id", "kickoff_utc", "team_id", "elo_before", "upstream_elo"]
    return m.loc[m.upstream_elo.notna(), keep].reset_index(drop=True)


def baseline_pool(by_season: dict[str, pd.DataFrame], order: list[str], season: str, gw: int,
                  pool_seasons: int) -> pd.DataFrame:
    """The results the no-skill baseline averages for target GW `gw` of `season`.

    The last `pool_seasons` seasons of `order` up to `season`: earlier ones in full, `season`
    up to and including GW `gw` - 1, the same pool the Elo goals model fits on at as-of g-1.
    """
    seasons = order[: order.index(season) + 1][-pool_seasons:]
    parts = [by_season[s] for s in seasons[:-1]]
    this = by_season[season]
    parts.append(this[this.gw <= gw - 1])
    return pd.concat(parts, ignore_index=True)


def read_stability(reads: dict[int, pd.DataFrame], season: str) -> dict[str, float]:
    """Compare every as-of read of `elo_ratings` with the last one.

    A read at as-of g must hold exactly the last read's rows of earlier seasons and of
    `season` up to GW g, with identical `elo_before` and `elo_after`. Counts rows compared,
    rows whose values changed, rows missing, rows extra (a later match in an earlier read).
    """
    last = reads[max(reads)]
    keys = ["season", "match_id", "team_id"]
    out = {"reads": len(reads), "rows": 0, "changed": 0, "missing": 0, "extra": 0,
           "max_abs_diff": 0.0}
    for g, read in reads.items():
        want = last[(last.season != season) | (last.gw <= g)]
        m = want.merge(read, on=keys, how="outer", suffixes=("", "_read"), indicator=True)
        both = m[m._merge == "both"]
        diff = np.maximum((both.elo_before - both.elo_before_read).abs(),
                          (both.elo_after - both.elo_after_read).abs())
        out["rows"] += len(read)
        out["changed"] += int((diff > 0).sum())
        out["missing"] += int((m._merge == "left_only").sum())
        out["extra"] += int((m._merge == "right_only").sum())
        out["max_abs_diff"] = max(out["max_abs_diff"], float(diff.max()) if len(diff) else 0.0)
    return out


def _current_ratings(ratings: pd.DataFrame, season: str) -> pd.Series:
    r = ratings[ratings.season == season].sort_values(["kickoff_utc", "match_id"], kind="stable")
    return r.drop_duplicates("team_id", keep="last").set_index("team_id").elo_after


def implied_coefficients(preds: pd.DataFrame, ratings: pd.DataFrame,
                         season: str) -> dict[str, float]:
    """Check brief 6.2's claims from the outputs of the two public functions alone.

    Regresses log `lambda_for` on (1, rating gap, home), with each club's current rating its
    last `elo_after` in `ratings` (the same as-of read). If the code is the Poisson on the Elo
    gap and home advantage it claims, the residual is zero. Also returns the largest error of
    `p_cs` against exp(-`lambda_against`) and of `lambda_against` against the opponent's
    `lambda_for`, and how many rows had a club with no rating.
    """
    cur = _current_ratings(ratings, season)
    gap = preds.team_id.map(cur) - preds.opponent_id.map(cur)
    ok = gap.notna()
    x = np.column_stack([np.ones(ok.sum()), gap[ok], preds.home[ok].astype(float)])
    y = np.log(preds.lambda_for[ok].to_numpy(dtype="float64"))
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    opp = preds.set_index(["match_id", "home"]).lambda_for
    mirror = preds.lambda_against.to_numpy() - opp.reindex(
        list(zip(preds.match_id, ~preds.home.astype(bool), strict=True))).to_numpy()
    return {"intercept": float(beta[0]), "gap": float(beta[1]), "home": float(beta[2]),
            "max_resid": float(np.abs(y - x @ beta).max()), "n": int(ok.sum()),
            "unrated": int((~ok).sum()),
            "p_cs_err": float(np.abs(preds.p_cs - np.exp(-preds.lambda_against)).max()),
            "mirror_err": float(np.nanmax(np.abs(mirror)))}
