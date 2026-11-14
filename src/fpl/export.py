"""The thin-slice outputs: players.csv, fixture_difficulty.csv, elo_ratings.csv and meta.csv.

    python -m fpl.export --out-dir DIR [--run-utc 2026-11-13T12:00:00Z]

Reads in live mode: the next and as-of gameweeks come from the deadline clock at the run time,
then the season is read once with `load_as_of`. Elo ratings and the Elo goals model reuse that
one read (`load_history`, then the pure cores `run_elo` and `goals_from_history`). Every check
runs before anything is written, so a failed run leaves the output directory untouched.
"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from fpl.clock import as_of_gameweek, next_gameweek
from fpl.features import live_deadlines
from fpl.frames import checked_merge
from fpl.ingest import ROOT, load_config, read_upstream_commit
from fpl.models.elo import EloSettings, SeasonRead, load_history, run_elo, team_rows
from fpl.models.team_goals import GoalsSettings, goals_from_history
from fpl.output_checks import STATUS_OK, TIME_FORMAT, CheckContext, check_outputs
from fpl.output_schema import OUTPUT_SCHEMA
from fpl.player_metrics import player_metrics
from fpl.schema import expected_dtype

log = logging.getLogger(__name__)

PIPELINE_CONFIG = ROOT / "config" / "pipeline.yaml"
MODEL_CONFIG = ROOT / "config" / "model.yaml"


def _conform(name: str, df: pd.DataFrame) -> pd.DataFrame:
    """`df` with the published file's columns, order and dtypes."""
    kinds = {c: expected_dtype(kind, nullable) for c, kind, nullable in OUTPUT_SCHEMA[name]}
    return df[list(kinds)].astype(kinds).reset_index(drop=True)


def _with_short_names(goals: pd.DataFrame, teams: pd.DataFrame) -> pd.DataFrame:
    """`goals` with `team` and `opponent`: `dim_team.short_name` of `team_id` and `opponent_id`."""
    names = teams[["team_id", "short_name"]]
    out = checked_merge(goals, names.rename(columns={"short_name": "team"}), on="team_id",
                        how="left", validate="many_to_one", name="goals -> dim_team (team)")
    return checked_merge(
        out, names.rename(columns={"team_id": "opponent_id", "short_name": "opponent"}),
        on="opponent_id", how="left", validate="many_to_one", name="goals -> dim_team (opponent)")


def _meta(run_utc: pd.Timestamp, commit: str, as_of_gw: int, next_gw: int,
          deadlines: pd.Series, mcfg: dict) -> pd.DataFrame:
    """The one meta.csv row. `status` is "ok": a run that fails a check publishes nothing."""
    return pd.DataFrame([{
        "run_utc": run_utc.strftime(TIME_FORMAT), "upstream_commit": commit,
        "current_gw": as_of_gw, "next_gw": next_gw,
        "next_deadline_utc": deadlines[next_gw].strftime(TIME_FORMAT),
        "model_version": str(mcfg["model_version"]), "max_horizon": int(mcfg["max_horizon"]),
        "backtest_mae_model": float("nan"), "backtest_mae_ep_next": float("nan"),
        "status": STATUS_OK,
    }])


def _check_context(history: Sequence[SeasonRead], deadlines: pd.Series, run_utc: pd.Timestamp,
                   next_gw: int, mcfg: dict, pcfg: dict) -> CheckContext:
    """What the checks compare with, built from the reads rather than from the outputs."""
    prem = pcfg["premier_league_tag"]
    finished = {}
    for read in history:
        fx = read.tables["fact_fixture"]
        done = fx[(fx.tournament == prem) & fx.finished & (fx.gw <= read.as_of_gw)]
        finished[read.season] = set(done.match_id)
    ov = pcfg["output_validation"]
    bounds = {
        "now_cost_m": pcfg["validation"]["now_cost_m"],
        "positions": list(pcfg["position_map"].values()), **ov,
    }
    current = history[-1]
    return CheckContext(
        run_utc=run_utc, season=current.season, as_of_gw=current.as_of_gw, next_gw=next_gw,
        max_horizon=int(mcfg["max_horizon"]), deadlines=deadlines, tables=current.tables,
        team_ids={r.season: set(r.tables["dim_team"].team_id) for r in history},
        finished_prem=finished, prem_tag=prem, bounds=bounds,
    )


def build_outputs(
    history: Sequence[SeasonRead], deadlines: pd.Series, run_utc: pd.Timestamp, commit: str, *,
    next_gw: int, mcfg: dict, pcfg: dict,
) -> tuple[dict[str, pd.DataFrame], CheckContext]:
    """The four output frames and the context to check them against. Pure.

    `history` is the Elo reads, oldest season first; the last is the current season in live
    mode at the as-of gameweek.
    """
    current = history[-1]
    prem = pcfg["premier_league_tag"]
    elo_settings = EloSettings.from_config(mcfg)
    elo = team_rows(run_elo(history, elo_settings, prem).matches)
    goals, _ = goals_from_history(history, elo_settings, GoalsSettings.from_config(mcfg), prem)
    outputs = {
        "players": _conform("players", player_metrics(current.tables, current.as_of_gw, prem)),
        "fixture_difficulty": _conform(
            "fixture_difficulty", _with_short_names(goals, current.tables["dim_team"])),
        "elo_ratings": _conform("elo_ratings", elo),
        "meta": _conform("meta", _meta(run_utc, commit, current.as_of_gw, next_gw, deadlines,
                                       mcfg)),
    }
    return outputs, _check_context(history, deadlines, run_utc, next_gw, mcfg, pcfg)


def publish(outputs: dict[str, pd.DataFrame], ctx: CheckContext, out_dir: Path) -> dict[str, Path]:
    """Check every output, then write the CSVs to `out_dir`.

    Raises `ValidationError` before touching `out_dir` if any check fails. Each file is
    written under a temporary name and renamed over the old one. A rename is atomic per file,
    not for the set: if one fails (on Windows, a file held open), earlier files are already
    new and later ones still old. The error is raised and the temporary files are removed.
    """
    check_outputs(outputs, ctx)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    temp = {name: out_dir / f".{name}.csv.tmp" for name in outputs}
    try:
        for name, df in outputs.items():
            df.to_csv(temp[name], index=False, lineterminator="\n")
    except BaseException:
        for path in temp.values():
            path.unlink(missing_ok=True)
        raise
    final = {name: out_dir / f"{name}.csv" for name in outputs}
    try:
        for name, path in temp.items():
            os.replace(path, final[name])
    finally:
        for path in temp.values():
            path.unlink(missing_ok=True)
    return final


def run_export(out_dir: Path, run_utc: datetime | None = None) -> dict[str, Path]:
    """Read the latest data live, build the four outputs, check and write them to `out_dir`."""
    pcfg, mcfg = load_config(PIPELINE_CONFIG), load_config(MODEL_CONFIG)
    run = pd.Timestamp(run_utc or datetime.now(UTC)).floor("s")
    run = run.tz_localize("UTC") if run.tzinfo is None else run.tz_convert("UTC")
    season = str(pcfg["current_season"])
    deadlines = live_deadlines(season)
    next_gw, as_of_gw = next_gameweek(deadlines, run), as_of_gameweek(deadlines, run)
    log.info("run %s: next gameweek %d, as-of gameweek %d", run.strftime(TIME_FORMAT), next_gw,
             as_of_gw)
    commit = read_upstream_commit(ROOT / pcfg["upstream"]["checkout_path"])
    history = load_history(season, as_of_gw, "live")
    outputs, ctx = build_outputs(history, deadlines, run, commit, next_gw=next_gw, mcfg=mcfg,
                                 pcfg=pcfg)
    paths = publish(outputs, ctx, out_dir)
    for name, df in outputs.items():
        log.info("%s: %d rows -> %s", name, len(df), paths[name])
    return paths


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--run-utc", type=datetime.fromisoformat, default=None,
                        help="pin the run time (ISO 8601); default is now")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_export(args.out_dir, args.run_utc)


if __name__ == "__main__":
    main()
