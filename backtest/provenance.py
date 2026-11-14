"""Provenance of a backtest run: commits, cleanliness, hashes, and where the report goes."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import yaml

from fpl.ingest import ROOT

HARNESS = Path(__file__).resolve().parent
SETTINGS = HARNESS / "config.yaml"


def _git(*args: str) -> str:
    res = subprocess.run(["git", *args], capture_output=True, text=True, check=True)
    return res.stdout.rstrip()


def status_summary(porcelain: str) -> str:
    """`git status --porcelain` output as one table-safe line: "yes" when clean, else
    "no: N modified, M untracked (paths)"."""
    lines = [ln for ln in porcelain.splitlines() if ln.strip()]
    if not lines:
        return "yes"
    paths = [ln[3:].split(" -> ")[-1].replace("|", "\\|") for ln in lines]
    untracked = sum(ln.startswith("??") for ln in lines)
    return (f"no: {len(lines) - untracked} modified, {untracked} untracked "
            f"({', '.join(paths)})")


def harness_sha256(folder: Path = HARNESS) -> str:
    """One hash of the harness: every `.py` file and `config.yaml` directly in `folder`, by name
    and content (the reports are left out)."""
    h = hashlib.sha256()
    for path in sorted([*folder.glob("*.py"), folder / "config.yaml"]):
        if path.exists():
            h.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def report_path(folder: Path, date: str) -> Path:
    """`{date}.md` in `folder`, or `{date}-2.md`, `{date}-3.md` ... if it exists already.

    A dated report can hold hand-written review notes, so a run never overwrites one.
    """
    out, n = folder / f"{date}.md", 2
    while out.exists():
        out, n = folder / f"{date}-{n}.md", n + 1
    return out


def run_info(pcfg: dict, root: Path = ROOT) -> dict[str, str]:
    """The code and data under test: commits, whether the model, loader, config, harness and
    upstream checkout match their commits (tracked and untracked files), and hashes of the
    configs and harness."""
    checkout = root / pcfg["upstream"]["checkout_path"]
    model_yaml = root / "config" / "model.yaml"
    version = (yaml.safe_load(model_yaml.read_text(encoding="utf-8")) or {}).get("model_version")
    status = ("-C", str(root), "status", "--porcelain", "--")
    return {
        "commit": _git("-C", str(root), "rev-parse", "HEAD"),
        "code_clean": status_summary(_git(*status, "src/fpl", "config")),
        "harness_clean": status_summary(_git(*status, "backtest",
                                             ":(exclude)backtest/reports")),
        "model_version": str(version) if version else "unset",
        "upstream_commit": _git("-C", str(checkout), "rev-parse", "HEAD"),
        "upstream_clean": status_summary(_git("-C", str(checkout), "status", "--porcelain")),
        "upstream_time": _git("-C", str(checkout), "log", "-1", "--format=%cI"),
        "model_yaml_sha256": hashlib.sha256(model_yaml.read_bytes()).hexdigest(),
        "settings_sha256": hashlib.sha256(SETTINGS.read_bytes()).hexdigest(),
        "harness_sha256": harness_sha256(),
    }
