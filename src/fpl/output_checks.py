"""Output validation (brief section 11, step 8) for the files `export` writes.

`output_problems` gathers every problem and never raises; `check_outputs` raises one
`ValidationError` listing them all, so a failed check stops the run before anything is written.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from fpl.output_checks_model import elo_problems, fixture_difficulty_problems
from fpl.output_schema import OUTPUT_KEYS, OUTPUT_SCHEMA
from fpl.schema import check_schema
from fpl.validate import ValidationError, key_problems

log = logging.getLogger(__name__)

STATUS_OK = "ok"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
COMMIT = re.compile(r"[0-9a-f]{7,64}")


@dataclass(frozen=True)
class CheckContext:
    """What the checks compare the outputs with.

    `tables` are the current season's processed tables at the as-of gameweek; `team_ids` and
    `finished_prem` give each season's `dim_team` ids and finished Premier League match ids
    that the Elo rows must cover. `bounds` holds `now_cost_m`, `positions`,
    `elo_rating_range`, `lambda_max` and `tolerance`.
    """

    run_utc: pd.Timestamp
    season: str
    as_of_gw: int
    next_gw: int
    max_horizon: int
    deadlines: pd.Series
    tables: dict[str, pd.DataFrame]
    team_ids: dict[str, set[int]]
    finished_prem: dict[str, set[str]]
    prem_tag: str
    bounds: dict


def _schema_problems(name: str, df: pd.DataFrame) -> list[str]:
    """Columns, dtypes, nulls, unique key and infinities of one file against its schema."""
    out = check_schema(df, name, OUTPUT_SCHEMA[name])
    out += key_problems(df, OUTPUT_KEYS[name], name)
    floats = [c for c, kind, _ in OUTPUT_SCHEMA[name] if kind == "float" and c in df.columns]
    for col in floats:
        inf = int(np.isinf(df[col].to_numpy(dtype="float64", na_value=np.nan)).sum())
        if inf:
            out.append(f"{name}.{col}: {inf} infinite values")
    return out


def _players_problems(players: pd.DataFrame, ctx: CheckContext) -> list[str]:
    """players.csv against `dim_player`/`dim_team` and the value bounds."""
    out = []
    dp, teams = ctx.tables["dim_player"], ctx.tables["dim_team"]
    if set(players.player_id) != set(dp.player_id):
        out.append("players: player_id set differs from dim_player")
    short = teams.set_index("team_id").short_name
    want = players.player_id.map(dp.set_index("player_id").team_id).map(short)
    bad_team = int((players.team != want).sum())
    if bad_team:
        out.append(f"players.team: {bad_team} values differ from dim_team.short_name")
    bad_pos = int((~players.position.isin(ctx.bounds["positions"])).sum())
    if bad_pos:
        out.append(f"players.position: {bad_pos} values not in {ctx.bounds['positions']}")
    lo, hi = ctx.bounds["now_cost_m"]
    if not players.price_m.between(lo, hi).all():
        out.append(f"players.price_m: values outside [{lo}, {hi}]")
    if not players.selected_pct.between(0, 100).all():
        out.append("players.selected_pct: values outside [0, 100]")
    if not players.chance_next.dropna().between(0, 100).all():
        out.append("players.chance_next: values outside [0, 100]")
    keepers = players[players.position == "GKP"]
    if (keepers.dc90 != 0).any():
        out.append("players.dc90: goalkeepers with a non-zero value")
    for col in ("minutes", "starts", "xg90", "xa90", "dc90"):
        if (players[col] < 0).any():
            out.append(f"players.{col}: negative values")
    return out


def _meta_problems(meta: pd.DataFrame, ctx: CheckContext) -> list[str]:
    """The meta row equals the run's context and its commit, version and status are valid."""
    if len(meta) != 1:
        return [f"meta: {len(meta)} rows, expected 1"]
    m = meta.iloc[0].to_dict()
    out = []
    expect = {"current_gw": ctx.as_of_gw, "next_gw": ctx.next_gw, "max_horizon": ctx.max_horizon,
              "run_utc": ctx.run_utc.strftime(TIME_FORMAT)}
    due = ctx.deadlines.get(ctx.next_gw)
    expect["next_deadline_utc"] = None if due is None else due.strftime(TIME_FORMAT)
    out += [f"meta.{k}: {m[k]!r}, expected {v!r}" for k, v in expect.items() if m[k] != v]
    if ctx.next_gw - 1 != ctx.as_of_gw:
        out.append("meta.current_gw is not next_gw - 1")
    if due is not None and not due > ctx.run_utc:
        out.append("meta.next_deadline_utc is not after run_utc")
    if not COMMIT.fullmatch(str(m["upstream_commit"])):
        out.append(f"meta.upstream_commit: {m['upstream_commit']!r} is not a commit hash")
    if not str(m["model_version"]).strip():
        out.append("meta.model_version: empty")
    if m["status"] != STATUS_OK:
        out.append(f"meta.status: {m['status']!r}, expected {STATUS_OK!r}")
    return out


def output_problems(outputs: dict[str, pd.DataFrame], ctx: CheckContext) -> list[str]:
    """Every problem with the four output files; empty if they all pass.

    Collects rather than stops at the first problem. A file with a schema problem skips its
    further checks. Raises only on input malformed beyond the schema (an unparseable
    `kickoff_utc`, a Premier League fixture with no club).
    """
    problems: list[str] = []
    sound: set[str] = set()
    for name in OUTPUT_SCHEMA:
        found = _schema_problems(name, outputs[name])
        problems += found
        if not found:
            sound.add(name)
    b = ctx.bounds
    names = dict(zip(ctx.tables["dim_team"].team_id, ctx.tables["dim_team"].short_name,
                     strict=True))
    if "players" in sound:
        problems += _players_problems(outputs["players"], ctx)
    if "meta" in sound:
        problems += _meta_problems(outputs["meta"], ctx)
    if "fixture_difficulty" in sound:
        problems += fixture_difficulty_problems(
            outputs["fixture_difficulty"], fixtures=ctx.tables["fact_fixture"],
            short_names=names, deadlines=ctx.deadlines, run=ctx.run_utc, next_gw=ctx.next_gw,
            max_horizon=ctx.max_horizon, prem_tag=ctx.prem_tag,
            tol=b["tolerance"], lambda_max=b["lambda_max"],
        )
    if "elo_ratings" in sound:
        problems += elo_problems(
            outputs["elo_ratings"], team_ids=ctx.team_ids, finished=ctx.finished_prem,
            season=ctx.season, as_of_gw=ctx.as_of_gw, run=ctx.run_utc,
            rating_range=b["elo_rating_range"], tol=b["tolerance"],
        )
    return problems


def check_outputs(outputs: dict[str, pd.DataFrame], ctx: CheckContext) -> None:
    """Raise `ValidationError` listing every problem; log and return if there are none."""
    problems = output_problems(outputs, ctx)
    if problems:
        raise ValidationError(problems)
    log.info("output checks passed for %s", ", ".join(outputs))
