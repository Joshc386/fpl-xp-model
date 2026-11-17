"""Cited score corrections (brief data rule 16).

A wrong upstream score is replaced only by an entry in `config/pipeline.yaml`
`score_corrections`. The entry names upstream's score, so the build fails when upstream
changes or fixes it and the entry must be removed or updated.
"""

from __future__ import annotations

import logging

import pandas as pd

from fpl.frames import CleanError

log = logging.getLogger(__name__)


def _fmt(score: list) -> str:
    """A score as "home-away", with "?" for a missing goal count."""
    return "-".join("?" if pd.isna(g) else str(int(g)) for g in score)


def apply_score_corrections(
    fixture: pd.DataFrame, corrections: list[dict], season: str, as_of_gw: int | None = None
) -> pd.DataFrame:
    """Return `fixture` with `home_goals` and `away_goals` corrected for this season's entries.

    Only goals change. Raises `CleanError` if a listed match is not in the fixtures, is not
    finished, or has an upstream score other than the entry's `upstream`. On an as-of read
    (`as_of_gw` given), a match after that gameweek is blanked to schedule only by ingest, so
    it is left alone rather than treated as unfinished.
    """
    out = fixture
    for entry in (e for e in corrections if e["season"] == season):
        mid = entry["match_id"]
        rows = out.index[out.match_id == mid]
        if len(rows) != 1:
            raise CleanError(
                f"score correction {mid} ({season}): found in {len(rows)} fixture rows, "
                "expected 1; remove or update the entry in config/pipeline.yaml"
            )
        i = rows[0]
        if not bool(out.at[i, "finished"]):
            if as_of_gw is not None and int(out.at[i, "gw"]) > as_of_gw:
                continue
            raise CleanError(f"score correction {mid} ({season}): the match is not finished")
        have = [out.at[i, "home_goals"], out.at[i, "away_goals"]]
        want = list(entry["upstream"])
        if any(pd.isna(g) for g in have) or [int(g) for g in have] != want:
            raise CleanError(
                f"score correction {mid} ({season}): upstream now has "
                f"{_fmt(have)}, the entry expects {_fmt(want)}. Upstream has changed or "
                "fixed it: remove or update the entry in config/pipeline.yaml"
            )
        if out is fixture:
            out = fixture.copy()
        out.at[i, "home_goals"], out.at[i, "away_goals"] = entry["corrected"]
        log.info(
            "score correction applied to %s (%s): %d-%d -> %d-%d (%s)", mid, season,
            *want, *entry["corrected"], entry["source"],
        )
    return out
