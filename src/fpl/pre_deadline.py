"""Build the pre-deadline view of `dim_player` from the upstream checkout's git history.

    python -m fpl.pre_deadline [--checkout DIR] [--out-dir DIR]

For each season in `config/pipeline.yaml` and each gameweek g from 2 to the last, it finds the
checkout's last commit before GW g's deadline, reads the master `players.csv` and
`playerstats.csv` from that commit with `git show`, and builds the `dim_player` rows by the
snapshot's own cleaning rules (`deadline_view.build_view_rows`). A backtest read at as-of g - 1
takes its `dim_player` from the rows of gameweek g (docs/data_contract.md, "Point-in-time
loader").

* The deadline is the earlier of the derived one (its first Premier League kickoff minus
  `loader.deadline_offset_minutes`) and FPL's `deadline_time` in the checkout's master
  `gameweek_summaries.csv`; a gap is logged. Each row stores it as `deadline_utc`.
* The commit is the newest one strictly before the deadline on the checkout's first-parent line
  (a side-branch commit merged later wasn't on upstream's main line before the deadline).

* It needs a full clone (the history is the input). It reads only git objects, never the working
  tree, so the checkout's state on disk doesn't matter; it never changes the checkout.
* A deadline after the checkout's newest commit takes that commit, and its rows are flagged
  `checkout_ends_early`.
* Any failing check fails the whole run and writes nothing: a commit's master files that break a
  cleaning rule are reported (gameweek and rule), never patched.
* `run_pipeline` and `update.yml` never run it, and live mode never reads its output.
"""

from __future__ import annotations

import argparse
import io
import logging
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

from fpl.asof import deadline_problems, deadlines
from fpl.deadline_view import (
    VIEW_COLUMNS,
    ViewError,
    build_view_rows,
    ends_early,
    pick_commit,
    write_view,
)
from fpl.ingest import ROOT, IngestError, load_config, read_upstream_commit
from fpl.schema import raw_columns, raw_dtypes

log = logging.getLogger(__name__)

GAMEWEEKS = "By Gameweek"


def _git(checkout: Path, *args: str) -> bytes:
    try:
        res = subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, check=False)
    except OSError as exc:
        raise ViewError(f"cannot run git: {exc}") from exc
    if res.returncode != 0:
        raise ViewError(f"git {' '.join(args)} failed: {res.stderr.decode(errors='replace')}")
    return res.stdout


def commit_history(checkout: Path) -> pd.DataFrame:
    """The commits of HEAD's first-parent line: `sha` and `time` (committer time, UTC), newest
    first. A commit merged in from a side branch isn't on the line, because a live run couldn't
    have seen it on upstream's main line before its deadline. Fails on a shallow clone."""
    if _git(checkout, "rev-parse", "--is-shallow-repository").decode().strip() == "true":
        raise ViewError(f"{checkout} is a shallow clone; the view needs a full clone "
                        "(git fetch --unshallow)")
    lines = _git(checkout, "log", "--first-parent", "--format=%H %cI", "HEAD").decode().splitlines()
    pairs = [ln.split() for ln in lines]
    return pd.DataFrame({
        "sha": [p[0] for p in pairs], "time": pd.to_datetime([p[1] for p in pairs], utc=True),
    })


def show_csv(checkout: Path, commit: str, rel: str, file: str) -> pd.DataFrame:
    """`rel` as it was at `commit`, read as `ingest.read_table` reads `file`."""
    need = set(raw_columns(file))
    df = pd.read_csv(
        io.BytesIO(_git(checkout, "show", f"{commit}:{rel}")), dtype=raw_dtypes(file),
        low_memory=False, usecols=lambda c: c in need,
    )
    absent = [c for c in raw_columns(file) if c not in df.columns]
    if absent:
        raise ViewError(f"{rel} at {commit[:8]} lacks columns {absent}")
    return df


def _folders(checkout: Path, head: str, base: str, n_gw: int, file: str) -> list[pd.DataFrame]:
    """`file` of every gameweek folder at `head`, each with its `snapshot_gw`."""
    return [
        show_csv(checkout, head, f"{base}/{GAMEWEEKS}/GW{g}/{file}.csv", file).assign(snapshot_gw=g)
        for g in range(1, n_gw + 1)
    ]


def season_inputs(
    checkout: Path, head: str, cfg: dict, scfg: dict
) -> tuple[pd.Series, pd.DataFrame, list[int]]:
    """The season's deadlines (by gameweek), its `teams` and the gameweeks where FPL's own
    `deadline_time` and the derived deadline differ, all read at `head`.

    The deadline used is the earlier of the derived one (`asof.deadlines`, from the schedule)
    and FPL's `deadline_time` in the master `gameweek_summaries.csv`; a gameweek FPL's file
    lacks uses the derived one. Every gap is logged. Fails if the derived deadlines don't
    strictly increase or a gameweek has none, or if a club's id and code differ between
    gameweek folders.
    """
    n_gw = int(scfg["gameweeks"])
    base = f"{cfg['upstream']['data_dir']}/{scfg['id']}"
    prem, offset = cfg["premier_league_tag"], cfg["loader"]["deadline_offset_minutes"]
    matches = pd.concat(_folders(checkout, head, base, n_gw, "matches"), ignore_index=True)
    problems = deadline_problems(matches, n_gw, prem, offset)
    derived = deadlines(matches, n_gw, prem, offset)
    if problems or derived.loc[2:].isna().any():
        raise ViewError(f"{scfg['id']}: deadlines can't be derived: {problems or 'a gap'}")
    all_teams = _folders(checkout, head, base, n_gw, "teams")
    pairs = pd.concat(all_teams)[["id", "code"]].drop_duplicates()
    if len(pairs) != len(all_teams[0]):
        raise ViewError(f"{scfg['id']}: a club's id and team code differ between gameweek folders")
    fpl = show_csv(checkout, head, f"{base}/gameweek_summaries.csv", "gameweek_summaries")
    theirs = pd.to_datetime(fpl.set_index("id").deadline_time, utc=True).reindex(derived.index)
    gaps = [int(g) for g in derived.index if theirs[g] != derived[g]]
    if gaps:
        log.warning("%s: FPL's deadline_time differs from the derived deadline (or is absent) "
                    "in GW %s; the earlier is used", scfg["id"], gaps)
    return derived.where(theirs.isna() | (derived <= theirs), theirs), all_teams[0], gaps


def build_season_view(
    checkout: Path, cfg: dict, scfg: dict
) -> tuple[pd.DataFrame, dict]:
    """The view of one season, and its report.

    Rows for every gameweek from 2 to the season's last: `dim_player`'s columns plus `gw`,
    `deadline_utc`, `upstream_commit`, `commit_utc` and `checkout_ends_early`. The report holds
    `gameweeks`, `rows`, `checkout_commit` (the head the history was read at),
    `checkout_ends_early` (the flagged gameweeks), `no_playerstats_row` (gameweek -> players
    dropped for lack of a playerstats row, only where there are some), `commits` (gameweek ->
    sha), `players` and `deadline_gaps` (gameweeks where FPL's deadline and the derived one
    differ).
    Raises `ViewError`, naming the gameweek,
    on any failed check, and `IngestError` if `checkout` isn't a git checkout.
    """
    read_upstream_commit(checkout)  # the folder must itself be a git repo's root
    history = commit_history(checkout)
    head = str(history.sha.iloc[0])
    season, base = scfg["id"], f"{cfg['upstream']['data_dir']}/{scfg['id']}"
    due, teams, gaps = season_inputs(checkout, head, cfg, scfg)
    val = cfg["validation"]
    parts: list[pd.DataFrame] = []
    report: dict = {"commits": {}, "no_playerstats_row": {}, "checkout_ends_early": []}
    master: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for gw in range(2, int(scfg["gameweeks"]) + 1):
        sha, when = pick_commit(history, due[gw])
        if sha not in master:
            master[sha] = (show_csv(checkout, sha, f"{base}/players.csv", "players"),
                           show_csv(checkout, sha, f"{base}/playerstats.csv", "playerstats"))
        try:
            rows, counts = build_view_rows(
                *master[sha], teams, cfg["position_map"], val["now_cost_m"],
                val["players_rows_per_snapshot"], val["playerstats_rows_snapshot"],
            )
        except ViewError as exc:
            raise ViewError(f"{season} GW{gw} (commit {sha[:8]}): {exc}") from exc
        early = ends_early(history, due[gw])
        parts.append(rows.assign(
            gw=gw, deadline_utc=due[gw].strftime("%Y-%m-%dT%H:%M:%SZ"), upstream_commit=sha,
            commit_utc=when.strftime("%Y-%m-%dT%H:%M:%SZ"), checkout_ends_early=early,
        ))
        report["commits"][gw] = sha
        if counts["no_playerstats_row"]:
            report["no_playerstats_row"][gw] = counts["no_playerstats_row"]
        if early:
            report["checkout_ends_early"].append(gw)
    view = pd.concat(parts, ignore_index=True)[VIEW_COLUMNS]
    report |= {"gameweeks": len(parts), "rows": len(view), "deadline_gaps": gaps,
               "checkout_commit": head, "players": view.groupby("gw").size().to_dict()}
    return view, report


def build_views(checkout: Path, cfg: dict, out_dir: Path) -> dict[str, dict]:
    """Build every configured season, then write them all (a failure writes nothing).

    Returns each season's report. The record next to each table names the head the history
    was read at, so a checkout that moves during the build can't be recorded wrongly. Fails
    if two seasons were read at different heads.
    """
    built = {s["id"]: build_season_view(checkout, cfg, s) for s in cfg["seasons"]}
    heads = {report["checkout_commit"] for _, report in built.values()}
    if len(heads) != 1:
        raise ViewError(f"the checkout moved during the build: read at {sorted(heads)}")
    for season, (view, report) in built.items():
        write_view(out_dir, season, view, checkout_commit=report["checkout_commit"])
    return {season: report for season, (_, report) in built.items()}


def main(argv: list[str] | None = None) -> int:
    """The command. Exits 1, with a message on stderr, on any failure."""
    parser = argparse.ArgumentParser(prog="python -m fpl.pre_deadline", description=__doc__)
    parser.add_argument("--checkout", type=Path, help="the upstream checkout (default: config)")
    parser.add_argument("--out-dir", type=Path, help="where to write (default: config)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config(ROOT / "config" / "pipeline.yaml")
    checkout = args.checkout or ROOT / cfg["upstream"]["checkout_path"]
    out_dir = args.out_dir or ROOT / cfg["paths"]["pre_deadline_dir"]
    started = time.monotonic()
    try:
        reports = build_views(checkout, cfg, out_dir)
    except (ViewError, IngestError) as exc:
        print(f"pre-deadline view failed: {exc}", file=sys.stderr)
        return 1
    for season, r in reports.items():
        print(f"{season}: {r['gameweeks']} gameweeks, {r['rows']} rows, "
              f"flagged {r['checkout_ends_early'] or 'none'}, "
              f"players without playerstats {r['no_playerstats_row'] or 'none'}, "
              f"deadline gaps {r['deadline_gaps'] or 'none'}")
    print(f"wrote {out_dir} in {time.monotonic() - started:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
