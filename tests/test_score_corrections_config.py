"""The real `score_corrections` entries are well formed (brief data rule 16). Runs on CI."""

from __future__ import annotations

import pytest

from fpl.ingest import ROOT, load_config

CFG = load_config(ROOT / "config" / "pipeline.yaml")
ENTRIES = CFG["score_corrections"]
SEASONS = [s["id"] for s in CFG["seasons"]]


def test_there_is_at_least_one_entry() -> None:
    assert ENTRIES


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["match_id"])
def test_an_entry_is_well_formed(entry: dict) -> None:
    assert set(entry) == {"match_id", "season", "upstream", "corrected", "source"}
    assert entry["season"] in SEASONS  # a misspelt season would silently switch it off
    for key in ("upstream", "corrected"):
        score = entry[key]
        assert len(score) == 2 and all(type(g) is int and g >= 0 for g in score), key
    assert entry["upstream"] != entry["corrected"]
    assert entry["source"].strip()
    # Premier League matches only: ingest leaves cup and European matches out of as-of reads.
    assert f"-{CFG['premier_league_tag']}-" in entry["match_id"]


def test_match_ids_are_unique_per_season() -> None:
    keys = [(e["season"], e["match_id"]) for e in ENTRIES]
    assert len(keys) == len(set(keys))
