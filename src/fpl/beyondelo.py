"""One-off pull of beyondELO's per-match club ratings and the `ext_beyondelo` table.

    python -m fpl.beyondelo [--config config/pipeline.yaml]

with `BEYONDELO_API_KEY` already set in the environment (never on the command line).

At most `beyondelo.max_requests` requests (about 6-9 are expected), none for what is already cached
in `data/external/beyondelo/raw/`. The processed tables and the previous seasons' teams files are
read first, so a missing input costs no request. Nothing is written until every season has
reconciled. To refresh a season, delete `raw/matches_{season}_p*.json`. Outside source for Josh's
Elo check, never a model input; read it with `load_beyondelo` (docs/data_contract.md, Outside
sources). The data is CC BY 4.0: anything derived from it that is published credits
"beyondELO (https://beyondelo.com)".
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from fpl.beyondelo_api import Client, Settings, pull
from fpl.beyondelo_build import (
    OUT_COLUMNS,
    BuildError,
    add_team_ids,
    build_season,
    find_unmapped,
    matches_frame,
)
from fpl.ingest import load_config

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]


def previous_season(season: str) -> str:
    """'2025-2026' -> '2024-2025'."""
    start, end = (int(x) for x in season.split("-"))
    return f"{start - 1}-{end - 1}"


def read_previous_codes(data_dir: Path, season: str) -> set[int]:
    """Upstream `code` of every club in the season before `season`.

    `code` is the club's identity across seasons (checked 2026-11-17: Chelsea is code 8 in 2024-25
    and 2025-26 with team ids 6 and 7); `id` is season-specific. The 2024-2025 file is
    `teams/teams.csv`, later seasons have `teams.csv`; read-only.
    """
    prev = previous_season(season)
    for path in (data_dir / prev / "teams.csv", data_dir / prev / "teams" / "teams.csv"):
        if path.exists():
            codes = pd.read_csv(path, usecols=["code"])["code"]
            if codes.empty or codes.isna().any():
                raise BuildError(f"{path} has no usable club codes")
            return {int(c) for c in codes}
    raise BuildError(f"no teams file for {prev} under {data_dir}: cannot flag promoted clubs")


def settings_from(bcfg: dict, root: Path) -> Settings:
    """The client's settings from the `beyondelo:` config."""
    return Settings(
        base_url=bcfg["base_url"].rstrip("/"), per_page=bcfg["per_page"],
        max_requests=bcfg["max_requests"], min_seconds=bcfg["min_seconds_between_requests"],
        timeout=bcfg["timeout_seconds"], raw_dir=root / bcfg["external_dir"] / "raw",
    )


def _read_inputs(cfg: dict, root: Path) -> dict[str, tuple[pd.DataFrame, pd.DataFrame, set[int]]]:
    """Our dim_team, fact_fixture and the previous season's codes, per season (no request yet)."""
    data_dir = root / cfg["upstream"]["checkout_path"] / cfg["upstream"]["data_dir"]
    out = {}
    for season in cfg["beyondelo"]["seasons"]:
        folder = root / cfg["paths"]["processed_dir"] / season
        for name in ("dim_team", "fact_fixture"):
            if not (folder / f"{name}.parquet").exists():
                missing = folder / f"{name}.parquet"
                raise BuildError(f"{missing} is missing: run fpl.run_pipeline first")
        out[season] = (pd.read_parquet(folder / "dim_team.parquet"),
                       pd.read_parquet(folder / "fact_fixture.parquet"),
                       read_previous_codes(data_dir, season))
    return out


def run(cfg: dict, root: Path = ROOT, client: Client | None = None) -> dict[str, Path]:
    """Pull (or read the cache), reconcile, then write `{season}.parquet` and reconciliation.csv."""
    bcfg = cfg["beyondelo"]
    seasons, aliases = bcfg["seasons"], bcfg.get("club_aliases") or {}
    inputs = _read_inputs(cfg, root)
    client = client or Client(settings_from(bcfg, root))
    tag = cfg["premier_league_tag"]
    held = {s: int((inputs[s][1]["tournament"] == tag).sum()) for s in seasons}
    pulled = pull(client, held)
    log.info("requests made this run: %d", client.requests_made)
    raw = settings_from(bcfg, root).raw_dir
    share = bcfg["max_wrong_direction_share"]
    frames = {s: matches_frame(pulled[s], share) for s in seasons}
    unmapped = sorted({n for s in seasons for n in find_unmapped(frames[s], inputs[s][0], aliases)})
    if unmapped:
        raise BuildError(f"beyondELO clubs not in dim_team: {unmapped}; add them to club_aliases")
    tables, recons = {}, []
    for s in seasons:
        dim_team, fixture, prev = inputs[s]
        try:
            tables[s], recon = build_season(
                add_team_ids(frames[s], dim_team, aliases), dim_team, fixture, prev, s,
                cfg["premier_league_tag"])
        except BuildError as exc:
            if not exc.refresh:
                raise
            files = raw / f"matches_{s}_p*.json"
            hint = f"beyondELO may not have caught up; to re-pull, delete {files}"
            raise BuildError(f"{exc} ({hint})") from exc
        recons.append(recon)
    out_dir = root / bcfg["external_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.concat(recons, ignore_index=True).to_csv(out_dir / "reconciliation.csv", index=False)
    for s, table in tables.items():
        table.to_parquet(out_dir / f"{s}.parquet", index=False)
        log.info("%s: %d rows, %d promoted", s, len(table), int(table["promoted"].sum()))
    return {s: out_dir / f"{s}.parquet" for s in tables}


def load_beyondelo(season: str, base_dir: Path | None = None) -> pd.DataFrame:
    """The `ext_beyondelo` table for `season`, with exactly the contract's columns.

    `base_dir` defaults to `beyondelo.external_dir` in config/pipeline.yaml.
    """
    if base_dir is None:
        cfg = load_config(ROOT / "config" / "pipeline.yaml")
        base_dir = ROOT / cfg["beyondelo"]["external_dir"]
    path = Path(base_dir) / f"{season}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist: run `python -m fpl.beyondelo`")
    df = pd.read_parquet(path)
    if list(df.columns) != OUT_COLUMNS:
        raise ValueError(f"{path} has columns {list(df.columns)}, expected {OUT_COLUMNS}")
    return df


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "pipeline.yaml")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for season, path in run(load_config(args.config)).items():
        log.info("%s written to %s", season, path)


if __name__ == "__main__":
    main()
