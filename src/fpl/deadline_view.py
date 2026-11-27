"""The pre-deadline view of `dim_player`: pure builders, the stored table, and its read.

A backtest read at as-of g takes `dim_player` from upstream's master `players.csv` and each
player's newest `playerstats.csv` row as they stood at the checkout's last commit before the
GW g+1 deadline, which is what a live run would have seen (docs/data_contract.md, "Point-in-time
loader"). `fpl.pre_deadline` builds the table from the checkout's git history; this module holds
the parts the loader needs too, so that `features.py` never imports git code (the checkout's
commit and the data copy's view are in `view_checkout`):

* the builders over frames (`newest_player_rows`, `build_view_rows`, `pick_commit`, `ends_early`),
  which apply the snapshot's own cleaning rules (`clean.build_dim_player`);
* the stored table, `{view_dir}/{season}.parquet`, and the record next to it,
  `{season}.json`, written last, which holds the checkout commit the table was built from;
* `read_view`, which refuses (never falls back to a snapshot) when the view is missing, lacks the
  gameweek, or was built from another checkout commit; and `apply_view`, which puts the view's
  players into a read.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from fpl.clean import build_dim_player
from fpl.frames import CleanError
from fpl.schema import PROCESSED_SCHEMA, check_schema, column_names

log = logging.getLogger(__name__)

COMMAND = "python -m fpl.pre_deadline"
# Inside a data copy (`features.use_data_copy`), the view is the copy's own: `{copy}/pre_deadline`.
COPY_VIEW_DIR = "pre_deadline"

EXTRA_COLUMNS = [
    ("gw", "int", False), ("deadline_utc", "str", False), ("upstream_commit", "str", False),
    ("commit_utc", "str", False), ("checkout_ends_early", "bool", False),
]
VIEW_SPEC = PROCESSED_SCHEMA["dim_player"] + EXTRA_COLUMNS
VIEW_COLUMNS = [c for c, _, _ in VIEW_SPEC]
DIM_COLUMNS = column_names("dim_player")


class ViewError(RuntimeError):
    """The pre-deadline view can't be built, or can't be used for a read."""


def view_paths(view_dir: Path, season: str) -> tuple[Path, Path]:
    """The table and its record of the checkout commit, for one season."""
    return Path(view_dir) / f"{season}.parquet", Path(view_dir) / f"{season}.json"


# ---- builders over frames -----------------------------------------------------------------


def newest_player_rows(playerstats: pd.DataFrame) -> pd.DataFrame:
    """Each player's row with the highest `gw`. Fails on a null id or gw, or two rows for one
    player and gameweek (the file has no single newest row to take)."""
    if playerstats[["id", "gw"]].isna().any().any():
        raise ViewError("master playerstats: null id or gw")
    dups = int(playerstats.duplicated(["id", "gw"]).sum())
    if dups:
        raise ViewError(f"master playerstats: {dups} duplicate (id, gw) keys")
    return playerstats.sort_values("gw").drop_duplicates("id", keep="last").reset_index(drop=True)


def _bounded(label: str, n: int, bounds: list[float]) -> list[str]:
    return [] if bounds[0] <= n <= bounds[1] else [f"{label}: {n} rows, outside {bounds}"]


def build_view_rows(
    players: pd.DataFrame, playerstats: pd.DataFrame, teams: pd.DataFrame,
    position_map: dict[str, str], price_bounds: list[float], row_bounds: list[int],
    stats_bounds: list[int],
) -> tuple[pd.DataFrame, dict[str, int]]:
    """The `dim_player` rows of one master version, by the snapshot's own cleaning rules.

    `players` and `playerstats` are the master files at one commit; each player's newest
    playerstats row is used. Returns the rows and the players dropped for lack of one. Checks
    what the snapshot's input checks do, and fails with every problem listed (nothing is
    imputed or converted): keys, the row counts of `players` and of the newest playerstats rows
    against `row_bounds` and `stats_bounds` (the snapshot's `players_rows_per_snapshot` and
    `playerstats_rows_snapshot`), prices in GBP m inside
    `price_bounds`, and the contract's schema. Raises `ViewError`.
    """
    newest = newest_player_rows(playerstats)
    problems = _bounded("master players", len(players), row_bounds)
    problems += _bounded("master playerstats", len(newest), stats_bounds)
    for col in ("player_id", "player_code"):
        dups = int(players[col].duplicated().sum())
        if dups or players[col].isna().any():
            problems.append(f"master players.{col}: {dups} duplicates or null values")
    lo, hi = price_bounds
    bad = int((~newest.now_cost.between(lo, hi)).sum())
    if bad:
        problems.append(f"master playerstats.now_cost: {bad} values null or outside "
                        f"[{lo}, {hi}] GBP m")
    if problems:
        raise ViewError("; ".join(problems))
    try:
        out, counts = build_dim_player(players, newest, teams, position_map)
    except CleanError as exc:
        raise ViewError(f"cleaning rule failed: {exc}") from exc
    problems = check_schema(out, "dim_player", PROCESSED_SCHEMA["dim_player"])
    if problems:
        raise ViewError("; ".join(problems))
    return out, counts


def pick_commit(commits: pd.DataFrame, deadline: pd.Timestamp) -> tuple[str, pd.Timestamp]:
    """The newest commit strictly before `deadline`, as (sha, commit time).

    `commits` (columns `sha` and `time`, UTC) is in history order, newest first. Fails if its
    times are not in order, or if no commit is before the deadline.
    """
    if not commits.time.is_monotonic_decreasing:
        raise ViewError("the commit history is not in time order (commit times must not "
                        "increase from the newest commit back)")
    before = commits[commits.time < deadline]
    if before.empty:
        raise ViewError(f"no commit before the deadline {deadline.isoformat()}")
    row = before.iloc[0]
    return str(row.sha), pd.Timestamp(row.time)


def ends_early(commits: pd.DataFrame, deadline: pd.Timestamp) -> bool:
    """Whether the checkout's newest commit is before `deadline`: upstream may still commit
    before it, so the view is the checkout's last state, not the true pre-deadline one."""
    return bool(commits.time.iloc[0] < deadline)


# ---- the stored table ---------------------------------------------------------------------


def _problems(view: pd.DataFrame) -> list[str]:
    out = check_schema(view, "dim_player_deadline", VIEW_SPEC)
    if out:
        return out
    dups = int(view.duplicated(["gw", "player_id"]).sum())
    return [f"dim_player_deadline: {dups} duplicate (gw, player_id) keys"] if dups else []


def write_view(
    view_dir: Path, season: str, view: pd.DataFrame, checkout_commit: str | None
) -> None:
    """Write the season's table, then its record of `checkout_commit` (None for a folder that
    is not a git checkout). Fails, writing nothing, if `view` breaks the schema. The old record
    goes first and the new one last, so a crash in between leaves the view missing (a table
    with no record counts as missing), never a new table beside an old record."""
    problems = _problems(view)
    if problems:
        raise ViewError("; ".join(problems))
    table, record = view_paths(view_dir, season)
    table.parent.mkdir(parents=True, exist_ok=True)
    record.unlink(missing_ok=True)  # a crash from here on leaves the view missing, not mismatched
    view.to_parquet(table, index=False)
    flagged = sorted(int(g) for g in view.loc[view.checkout_ends_early, "gw"].unique())
    info = {
        "season": season, "checkout_commit": checkout_commit,
        "built_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gameweeks": sorted(int(g) for g in view.gw.unique()), "checkout_ends_early": flagged,
    }
    record.write_text(json.dumps(info) + "\n", encoding="utf-8")


def _conform(view: pd.DataFrame) -> pd.DataFrame:
    """The parquet round trip with the schema's dtypes (nullable integers, plain strings)."""
    out = view.copy()
    for col, kind, nullable in VIEW_SPEC:
        if col not in out.columns:
            continue
        if kind == "int":
            out[col] = out[col].astype("Int64" if nullable else "int64")
        elif kind == "float":
            out[col] = out[col].astype("float64")
        elif kind == "bool":
            out[col] = out[col].astype(bool)
    return out


def read_view(
    view_dir: Path, season: str, gw: int, checkout_commit: str | None
) -> pd.DataFrame:
    """The view's rows for deadline gameweek `gw`: `dim_player`'s columns plus `gw`,
    `deadline_utc`, `upstream_commit`, `commit_utc` and `checkout_ends_early`.

    `checkout_commit` is the commit of the checkout the read uses (None if it is not a git
    checkout). Raises `ViewError`, naming the command to run, if the view is missing, was
    built from another commit than `checkout_commit` (so a real view never matches a folder
    that is not a git checkout), or lacks `gw`; and if its table breaks the schema.
    """
    table, record = view_paths(view_dir, season)
    fix = f"run `{COMMAND}`"
    if not table.exists() or not record.exists():
        have = [p.name for p in (table, record) if not p.exists()]
        raise ViewError(f"no pre-deadline view for {season} in {view_dir}: missing {have}; {fix}")
    built_from = json.loads(record.read_text(encoding="utf-8")).get("checkout_commit")
    if built_from != checkout_commit:
        raise ViewError(
            f"the pre-deadline view for {season} is stale: built from checkout commit "
            f"{built_from}, the checkout is at {checkout_commit or 'no git commit'}; {fix}"
        )
    rows = _conform(pd.read_parquet(table, filters=[("gw", "==", int(gw))]))
    if rows.empty:
        raise ViewError(f"the pre-deadline view for {season} lacks GW{gw}; {fix}")
    problems = _problems(rows)
    if problems:
        raise ViewError(f"the pre-deadline view for {season} is malformed: {'; '.join(problems)}")
    return rows.reset_index(drop=True)


def check_before_deadline(view: pd.DataFrame, gw: int, derived: pd.Timestamp) -> None:
    """Fail unless every row's commit is strictly before both its own `deadline_utc` (the
    earlier of the derived deadline and FPL's, as the build stored it) and `derived`, the
    deadline of GW `gw` from the read's own schedule."""
    if pd.isna(derived):
        raise ViewError(f"GW{gw} has no deadline to check the pre-deadline view against")
    stored = pd.to_datetime(view.deadline_utc, utc=True)
    limit = stored.where(stored <= derived, derived)
    late = pd.to_datetime(view.commit_utc, utc=True) >= limit
    if late.any():
        raise ViewError(f"the pre-deadline view for GW{gw} holds {int(late.sum())} rows from "
                        f"a commit at or after the deadline ({derived.isoformat()} derived, "
                        f"{view.deadline_utc.iloc[0]} stored)")


def apply_view(
    snapshot: pd.DataFrame, view: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, int]]:
    """The read's `dim_player`: the view's players and columns, in player order.

    A player in the snapshot's `dim_player` but not in the view is dropped from it (counted as
    `dropped`); the fact tables keep his rows. A player in the view but not in the snapshot is
    kept (`not_in_snapshot`).
    """
    out = view[DIM_COLUMNS].sort_values("player_id").reset_index(drop=True)
    counts = {
        "dropped": int((~snapshot.player_id.isin(out.player_id)).sum()),
        "not_in_snapshot": int((~out.player_id.isin(snapshot.player_id)).sum()),
    }
    return out, counts
