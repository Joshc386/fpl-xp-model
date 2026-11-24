"""The point-in-time loader and the generic, model-agnostic features.

Outside the data-engineer's own code, every agent reads data through `load_as_of`. It is
the main guard against leakage:

* **backtest** builds the processed tables from the `GW{as_of_gw}` snapshot and earlier
  folders only. It never opens a master file. Matches in later gameweeks are schedule only.
* **live** is the same, then overlays the current-state fields of `dim_player` (status, news,
  chance of playing, price, and the price-change and transfer counts) from the master
  playerstats, so projections see the latest team news.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

import pandas as pd

from fpl.clean import build_season
from fpl.clock import as_of_gameweek, next_gameweek, parse_deadlines
from fpl.frames import checked_merge
from fpl.ingest import ROOT, load_config, read_season, upstream_data_dir
from fpl.master import read_deadlines, read_master_state
from fpl.overlay import overlay_current_state
from fpl.validate import validate_inputs
from fpl.validate_tables import validate_tables

log = logging.getLogger(__name__)

MODES = ("backtest", "live")


# The upstream data folder (the one holding the season folders) that `use_data_copy` sets.
_DATA_COPY: ContextVar[Path | None] = ContextVar("fpl_data_copy", default=None)


@contextmanager
def use_data_copy(data_dir: Path) -> Iterator[None]:
    """Read upstream data from `data_dir` instead of the configured checkout (tests and the
    backtest harness only).

    `data_dir` is the folder that holds the season folders (the checkout's `data/`). Inside the
    block, `load_as_of`, `live_deadlines` and `live_gameweeks` take their data from it, also
    when called by the model's public functions, which pass no `root` or `cfg`. A call given
    its own `root` or `cfg` is unaffected. The previous setting is restored on exit, including
    after an exception. Blocks nest. The setting is per thread or task: a worker thread
    started inside the block does not see it and reads the real checkout.
    """
    token = _DATA_COPY.set(Path(data_dir))
    try:
        yield
    finally:
        _DATA_COPY.reset(token)


def _config(cfg: dict | None, root: Path) -> dict:
    return cfg if cfg is not None else load_config(root / "config" / "pipeline.yaml")


def _resolve(cfg: dict | None, root: Path | None) -> tuple[dict, Path]:
    """The pipeline config and the upstream data folder for one loader call.

    An explicit `root` or `cfg` always means the checkout it names; otherwise the data copy of
    `use_data_copy` applies if there is one.
    """
    copy = _DATA_COPY.get() if cfg is None and root is None else None
    root = ROOT if root is None else root
    cfg = _config(cfg, root)
    return cfg, copy if copy is not None else upstream_data_dir(cfg, root)


def _season_config(cfg: dict, season: str) -> dict:
    for scfg in cfg["seasons"]:
        if scfg["id"] == season:
            return scfg
    raise ValueError(f"unknown season {season!r}; configured: {[s['id'] for s in cfg['seasons']]}")


def load_as_of(
    season: str, as_of_gw: int, mode: str, *, cfg: dict | None = None, root: Path | None = None
) -> dict[str, pd.DataFrame]:
    """The seven processed tables as they stood at the end of `GW{as_of_gw}`.

    `mode` is "backtest" or "live". Backtest holds every match with `gw` up to `as_of_gw`, in
    any competition (a cup or European match's `gw` is the gameweek it was played in, so it
    may come from a later folder; see `asof.py`), with `dim_player` from the `as_of_gw`
    snapshot and never opens a master file. Later Premier League fixtures are schedule only
    (`finished` and `stats_complete` false, results, xG and Elo null); later cup and European
    matches are left out. Upstream Elo exists for Premier League matches only. Live is
    identical, except that `dim_player` status, news, `chance_next`, `price_tenths` and the
    four price-change and transfer counts (`overlay.OVERLAID`) come from the master playerstats.
    `as_of_gw` may be ahead of the newest folder with data; what exists is returned.
    `fact_shot` and `fact_player_spell` come from the `shots.csv` and `incidents.csv` of the
    folders up to `as_of_gw` only, hold only complete Premier League matches of the read, and
    are not overlaid in live mode. Their checks against matches.csv are not run here.
    Raises `ValueError` for a bad mode, season or gameweek, and the validation errors of a
    failed check.
    """
    cfg, data_dir = _resolve(cfg, root)
    scfg = _season_config(cfg, season)
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    if not 0 <= as_of_gw <= int(scfg["gameweeks"]):
        raise ValueError(f"as_of_gw must be 0..{scfg['gameweeks']}, got {as_of_gw}")
    raw = read_season(
        data_dir, scfg, commit="as-of", as_of_gw=as_of_gw, prem_tag=cfg["premier_league_tag"],
        offset_minutes=cfg["loader"]["deadline_offset_minutes"],
    )
    validate_inputs(raw, cfg, scfg)
    tables = build_season(raw, cfg).tables
    if mode == "live":
        master = read_master_state(data_dir / season)
        tables["dim_player"] = overlay_current_state(
            tables["dim_player"], master, cfg["validation"]["now_cost_m"]
        )
    validate_tables(tables, cfg["premier_league_tag"])
    return tables


def live_deadlines(
    season: str, *, cfg: dict | None = None, root: Path | None = None
) -> pd.Series:
    """Every gameweek's deadline (UTC timestamps, by gameweek), from the master deadlines."""
    cfg, data_dir = _resolve(cfg, root)
    scfg = _season_config(cfg, season)
    summaries = read_deadlines(data_dir / season)
    return parse_deadlines(summaries, n_gw=int(scfg["gameweeks"]))


def live_gameweeks(
    season: str, run_utc: datetime, *, cfg: dict | None = None, root: Path | None = None
) -> tuple[int, int]:
    """(next gameweek, as-of gameweek) at `run_utc`, from the master deadlines (live only)."""
    deadlines = live_deadlines(season, cfg=cfg, root=root)
    return next_gameweek(deadlines, run_utc), as_of_gameweek(deadlines, run_utc)


def _check_windows(windows: Sequence[int]) -> list[int]:
    out = [int(w) for w in windows]
    if not out or min(out) < 1 or len(set(out)) != len(out) or out != list(windows):
        raise ValueError(f"windows must be distinct positive integers, got {list(windows)}")
    return out


def recent_minutes(
    tables: dict[str, pd.DataFrame], as_of_gw: int, windows: Sequence[int],
    prem_tag: str | None = None,
) -> pd.DataFrame:
    """Recent FPL minutes and starts per player, over each window of gameweeks.

    For each window N: the totals of `minutes` and `starts`, and `fixtures` (the club's
    Premier League fixtures), over the player's last N gameweeks up to `as_of_gw` in which
    his club (`fact_player_gw.team_id` of that gameweek) had a Premier League fixture. A
    double gameweek counts as one gameweek; a blank gameweek is skipped; a window longer
    than the history just covers all of it. Only gameweeks the player has a row for count,
    so a gameweek still to finish for his club is not yet one of them, and a row with no
    club (a player missing from that snapshot) is skipped. Players with no such gameweek
    get zeros. Returns one row per player and window: `player_id`, `window`, `minutes`,
    `starts`, `fixtures`.
    """
    wins = _check_windows(windows)
    prem_tag = prem_tag or _config(None, ROOT)["premier_league_tag"]
    fx = tables["fact_fixture"]
    fx = fx[fx.tournament == prem_tag]
    sides = pd.concat([
        fx[["gw", col]].rename(columns={col: "team_id"}) for col in ("home_team_id", "away_team_id")
    ]).dropna()
    clubs = sides.groupby(["team_id", "gw"]).size().rename("fixtures").reset_index()
    gws = tables["fact_player_gw"]
    gws = gws[gws.gw <= as_of_gw][["player_id", "team_id", "gw", "minutes", "starts"]]
    rows = checked_merge(
        gws, clubs.astype({"team_id": "Int64"}), on=["team_id", "gw"], how="left",
        validate="many_to_one", name="fact_player_gw -> club fixtures",
    )
    rows["fixtures"] = rows["fixtures"].fillna(0).astype("int64")
    rows = rows[rows.fixtures > 0].sort_values(["player_id", "gw"], ascending=[True, False])
    rows["recency"] = rows.groupby("player_id").cumcount()
    players = pd.Index(
        sorted(set(tables["dim_player"].player_id) | set(gws.player_id)), name="player_id"
    )
    parts = []
    for n in wins:
        total = rows[rows.recency < n].groupby("player_id")[["minutes", "starts", "fixtures"]].sum()
        parts.append(total.reindex(players, fill_value=0).astype("int64").assign(window=n))
    return pd.concat(parts).reset_index()[["player_id", "window", "minutes", "starts", "fixtures"]]
