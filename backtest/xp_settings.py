"""The xP backtest's settings: which model and components to call, which seasons the run
touches (and the holdout refusal), the reads that raise by design, and the config hashes the
report records. Nothing here reads data."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from backtest.elo_data import HarnessError
from backtest.xp_components import resolve
from fpl.ingest import ROOT

ModelFn = Callable[[str, int, str], pd.DataFrame]

OUTCOMES = {"player": {"p60", "cs", "goals"}, "team": {"goals_for"}}


class HoldoutError(HarnessError):
    """A holdout season was asked for without the explicit holdout switch."""


@dataclass(frozen=True)
class Predictors:
    """The model and the components under test (None or absent when not built)."""

    model: ModelFn | None = None
    components: dict[str, ModelFn] = field(default_factory=dict)


def check_components(s: dict) -> None:
    """Raises `HarnessError` for a component whose kind, outcome or bins aren't configured."""
    for name, c in s["components"].items():
        kind, outcome = c.get("kind"), c.get("outcome")
        known = kind in OUTCOMES and outcome in OUTCOMES[kind]
        if not known or c.get("edges") not in s["diagnostics"] or "column" not in c:
            raise HarnessError(f"component {name!r} needs column, kind {sorted(OUTCOMES)}, an "
                               "outcome for its kind and edges naming a diagnostics bin list")


def load_predictors(s: dict, baselines_only: bool) -> Predictors:
    """The configured model and components that are built; none for a baselines-only run."""
    check_components(s)
    if baselines_only:
        return Predictors()
    comps = {n: resolve(c["callable"]) for n, c in s["components"].items()}
    return Predictors(resolve(s["model"]["callable"]), {n: f for n, f in comps.items() if f})


def touched_seasons(s: dict) -> set[str]:
    """Every season the run reads: the walk-forward (and its diagnostics) and the leakage
    cases."""
    return {x["id"] for x in s["seasons"]} | {k["season"] for k in s["perturbation"]["cases"]}


def check_holdout(s: dict, allow_holdout: bool) -> None:
    """Raises `HoldoutError`, before any read, if the run would touch a holdout season and the
    switch is off."""
    held = sorted(touched_seasons(s) & set(s["holdout_seasons"]))
    if held and not allow_holdout:
        raise HoldoutError(f"{held} is the holdout: it is scored only with --holdout, after "
                           "Josh has approved the look and it is logged in docs/decisions.md")


def expected_skips(s: dict) -> dict[str, dict[str, dict[int, type[Exception]]]]:
    """`expected_skips` with each "module:Class" resolved: the reads that raise by design."""
    out: dict[str, dict[str, dict[int, type[Exception]]]] = {}
    for fn, by_season in (s.get("expected_skips") or {}).items():
        for season, by_gw in by_season.items():
            for g, name in by_gw.items():
                cls = resolve(name)
                if not (isinstance(cls, type) and issubclass(cls, Exception)):
                    raise HarnessError(f"expected skip {name!r} is not an exception class")
                out.setdefault(fn, {}).setdefault(season, {})[int(g)] = cls
    return out


def config_hashes(root: Path = ROOT) -> dict[str, str]:
    """sha256 of the two configs the run reads besides model.yaml (which `run_info` hashes)."""
    return {f"{name}_yaml_sha256":
            hashlib.sha256((root / "config" / f"{name}.yaml").read_bytes()).hexdigest()
            for name in ("pipeline", "scoring")}
