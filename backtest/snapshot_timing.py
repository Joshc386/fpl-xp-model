"""Snapshot timing (brief section 7, "Known limitation (snapshot timing)").

A GW g-1 snapshot predicts gameweek g. Upstream may rewrite a snapshot's `playerstats.csv`
after the GW g deadline, and then its status, chance of playing, price and `ep_next` can
describe a later time. The check compares, per snapshot, the version the loader reads (the
checkout's) with the last version committed before the GW g deadline, in the upstream
checkout's own git history:

* **late:** no version before the deadline, or more than `late_share` of the players in
  both versions differ in any compared field;
* **refers to:** the gameweek whose pre-deadline snapshot's `ep_next` the read version
  matches best (share of players with an equal value), so a late snapshot's `ep_next` is
  shown to be for g, g+1 or a later gameweek.

Values are compared as the loader reads them: prices in £m (an old version written in
tenths is converted), a blank chance of playing as 100. This is an audit of the data's
timing, read from git, never a predictor input; predictors read only through `load_as_of`.
"""

from __future__ import annotations

import io
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

GAMEWEEKS = "By Gameweek"


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True)
    return res.stdout.decode("utf-8")


def deadlines(fx: pd.DataFrame, prem: str, offset_minutes: int) -> pd.Series:
    """Each gameweek's deadline: its first Premier League kickoff minus the offset (as the
    loader derives it, data contract "Point-in-time loader")."""
    league = fx[fx.tournament == prem]
    first = pd.to_datetime(league.kickoff_utc, utc=True).groupby(league.gw).min()
    return first - pd.Timedelta(minutes=offset_minutes)


def _versions(repo: Path, rel: str) -> list[tuple[str, pd.Timestamp]]:
    """(commit, commit time) of every version of `rel`, newest first in history order (two
    commits can share a second, so times don't order them)."""
    lines = _git(repo, "log", "--format=%H %cI", "--", rel).splitlines()
    return [(h, pd.Timestamp(t).tz_convert("UTC")) for h, t in (ln.split() for ln in lines)]


def _read(repo: Path, commit: str, rel: str, fields: Sequence[str]) -> pd.DataFrame:
    """The version's fields by player id, normalised as the loader reads them."""
    df = pd.read_csv(io.StringIO(_git(repo, "show", f"{commit}:{rel}")), dtype=str,
                     keep_default_na=False)
    out = pd.DataFrame(index=pd.Index(pd.to_numeric(df.id).astype("int64"), name="id"))
    for f in fields:
        col = df[f].to_numpy()
        if f == "status":
            out[f] = col
            continue
        v = pd.to_numeric(pd.Series(col).replace("", None), errors="coerce").to_numpy()
        if f == "now_cost":
            v = np.round(np.where(v > 30, v / 10, v), 1)
        if f == "chance_of_playing_next_round":
            v = np.where(np.isnan(v), 100.0, v)
        out[f] = v
    return out


def _differs(a: pd.Series, b: pd.Series) -> pd.Series:
    if not (pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b)):
        return a.astype(str) != b.astype(str)
    both_nan = a.isna() & b.isna()
    return ~(np.isclose(a, b, rtol=0, atol=1e-9) | both_nan)


def _match_share(a: pd.Series, b: pd.Series) -> float:
    ids = a.index.intersection(b.index)
    return float((~_differs(a[ids], b[ids])).mean()) if len(ids) else 0.0


def snapshot_timing(repo: Path, data_dir: str, season: str, deadline: pd.Series,
                    snapshots: Iterable[int], fields: Sequence[str],
                    late_share: float) -> pd.DataFrame:
    """One row per snapshot s (predicting s + 1): its last write, the deadline, the share of
    players whose each field differs from the pre-deadline version, `late`, `refers_to`,
    `refers_share` and a `note`. `repo` is the upstream checkout."""
    read_now, before = {}, {}
    rows = []
    for s in snapshots:
        rel = f"{data_dir}/{season}/{GAMEWEEKS}/GW{s}/playerstats.csv"
        versions = _versions(repo, rel)
        row = {"snapshot": s, "target": s + 1, "deadline": deadline.get(s + 1),
               "last_write": versions[0][1] if versions else None, "players": 0, "note": ""}
        if not versions:
            rows.append(row | {"late": True, "note": "no snapshot in the history"})
            continue
        read_now[s] = _read(repo, versions[0][0], rel, fields)
        row["players"] = len(read_now[s])
        pre = next((v for v in versions if v[1] < deadline[s + 1]), None)
        if pre is None:
            row |= {"late": True, "note": "no version before the deadline"}
        else:
            before[s] = _read(repo, pre[0], rel, fields)
            ids = read_now[s].index.intersection(before[s].index)
            share = {f: float(_differs(read_now[s].loc[ids, f], before[s].loc[ids, f]).mean())
                     for f in fields}
            row |= {f"changed_{f}": v for f, v in share.items()}
            row["late"] = max(share.values()) > late_share
        rows.append(row)
    for row in rows:
        s = row["snapshot"]
        now = read_now.get(s)
        scores = {} if now is None else {k: _match_share(now.ep_next, b.ep_next)
                                         for k, b in before.items()}
        best = max(scores, key=lambda k: (scores[k], k == s, -k)) if scores else None
        row["refers_to"] = best + 1 if best is not None else None
        row["refers_share"] = scores.get(best, np.nan) if best is not None else np.nan
    return pd.DataFrame(rows)
