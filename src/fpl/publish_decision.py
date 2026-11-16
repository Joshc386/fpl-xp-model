"""Whether a run should publish: skip when upstream hasn't moved since the last publish.

    python -m fpl.publish_decision [--checkout DIR] [--meta outputs/meta.csv]

Compares the upstream checkout's commit with `upstream_commit` in the published meta.csv.
It prints `publish=true` or `publish=false` and, under GitHub Actions, appends the same line
to `$GITHUB_OUTPUT`. Both answers exit 0, so a skipped run stays green. A meta.csv that
exists but can't be used exits non-zero with a message: the run fails rather than guesses.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

from fpl.ingest import ROOT, IngestError, load_config, read_upstream_commit

PIPELINE_CONFIG = ROOT / "config" / "pipeline.yaml"
DEFAULT_META = ROOT / "outputs" / "meta.csv"


class PublishDecisionError(RuntimeError):
    """The published meta.csv, or the checkout's SHA, can't be used to decide."""


def _norm(sha: str) -> str:
    """A SHA compared without case or surrounding whitespace."""
    return sha.strip().lower()


def published_commit(meta_path: Path) -> str | None:
    """`upstream_commit` of the published meta.csv, or None if there's no file yet."""
    meta_path = Path(meta_path)
    if not meta_path.exists():
        return None
    try:
        meta = pd.read_csv(meta_path, dtype=str, keep_default_na=False)
    except (OSError, ValueError) as exc:
        raise PublishDecisionError(f"cannot read {meta_path}: {exc}") from exc
    if "upstream_commit" not in meta.columns:
        raise PublishDecisionError(f"{meta_path} has no upstream_commit column")
    if len(meta) != 1:
        raise PublishDecisionError(
            f"{meta_path} must have exactly one upstream_commit value, found {len(meta)} rows")
    value = _norm(meta["upstream_commit"].iloc[0])
    if not value:
        raise PublishDecisionError(f"{meta_path} has an empty upstream_commit")
    return value


def decide(upstream_sha: str, meta_path: Path) -> bool:
    """True to publish: no meta.csv yet, or its commit differs from `upstream_sha`."""
    current = _norm(upstream_sha)
    if not current:
        raise PublishDecisionError("the upstream SHA is empty")
    published = published_commit(meta_path)
    return published is None or published != current


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    default_checkout = ROOT / load_config(PIPELINE_CONFIG)["upstream"]["checkout_path"]
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--checkout", type=Path, default=default_checkout)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    args = parser.parse_args(argv)
    try:
        sha = read_upstream_commit(args.checkout)
        publish = decide(sha, args.meta)
    except (PublishDecisionError, IngestError) as exc:
        sys.exit(f"publish decision failed: {exc}")
    line = f"publish={'true' if publish else 'false'}"
    print(f"upstream {sha}: {line}")
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")


if __name__ == "__main__":
    main()
