"""Local entry point: ingest, validate and clean both seasons.

    python -m fpl.run_pipeline [--config config/pipeline.yaml]

Nothing is written until every season has passed every check, and nothing is ever
written to outputs/.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from fpl.clean import BuiltSeason, build_season
from fpl.ingest import RawSeason, load_config, read_season, read_upstream_commit
from fpl.validate import check_match_ids_disjoint, validate_inputs
from fpl.validate_tables import validate_tables

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]


def write_season(raw: RawSeason, built: BuiltSeason, processed_dir: Path) -> Path:
    """Write a season's Parquet tables, reconciliation.csv and manifest.json."""
    out = Path(processed_dir) / raw.season
    out.mkdir(parents=True, exist_ok=True)
    for name, df in built.tables.items():
        df.to_parquet(out / f"{name}.parquet", index=False)
    built.reconciliation.to_csv(out / "reconciliation.csv", index=False)
    manifest = {
        "season": raw.season,
        "upstream_commit": raw.upstream_commit,
        "latest_gw": raw.latest_gw,
        "built_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rows": {name: len(df) for name, df in built.tables.items()},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out


def run(cfg: dict, root: Path = ROOT) -> dict[str, Path]:
    """Ingest, validate and clean every configured season, then write the tables."""
    checkout = root / cfg["upstream"]["checkout_path"]
    commit = read_upstream_commit(checkout)
    log.info("upstream commit %s", commit)
    data_dir = checkout / cfg["upstream"]["data_dir"]
    built: list[tuple[RawSeason, BuiltSeason]] = []
    for scfg in cfg["seasons"]:
        raw = read_season(
            data_dir, scfg, commit, prem_tag=cfg["premier_league_tag"],
            offset_minutes=cfg["loader"]["deadline_offset_minutes"],
        )
        validate_inputs(raw, cfg, scfg)
        result = build_season(raw, cfg)
        validate_tables(result.tables, cfg["premier_league_tag"])
        built.append((raw, result))
    check_match_ids_disjoint([raw for raw, _ in built])
    return {
        raw.season: write_season(raw, result, root / cfg["paths"]["processed_dir"])
        for raw, result in built
    }


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
