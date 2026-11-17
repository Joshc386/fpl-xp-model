"""Builders and fakes for the beyondELO tests. All invented: no real beyondELO data."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from fpl import beyondelo_api as api

KEY = "SECRET-KEY-123"
FIXTURES = Path(__file__).parent / "fixtures" / "beyondelo"
NAMES = ["Alpha", "Beta", "Gamma", "Delta"]


def dim_team() -> pd.DataFrame:
    """Four clubs: ids 1-4, codes 10-13."""
    return pd.DataFrame({
        "team_id": [1, 2, 3, 4], "team_code": [10, 11, 12, 13], "name": NAMES,
        "short_name": ["ALP", "BET", "GAM", "DEL"], "upstream_elo": [1800.0] * 4,
    })


def fixture() -> pd.DataFrame:
    """Three finished Premier League matches, one scheduled, and one cup match."""
    rows = [
        ("m1", 1, "2025-08-16T16:30:00Z", "prem", 1, 2, 2, 1, True),
        ("m2", 1, "2025-08-16T19:00:00Z", "prem", 3, 4, 0, 0, True),
        ("m3", 2, "2025-08-23T14:00:00Z", "prem", 2, 3, 1, 3, True),
        ("m4", 3, "2025-08-30T14:00:00Z", "prem", 4, 1, None, None, False),
        ("c1", 3, "2025-08-27T19:00:00Z", "cup", 1, 3, 1, 0, True),
    ]
    df = pd.DataFrame(rows, columns=[
        "match_id", "gw", "kickoff_utc", "tournament", "home_team_id", "away_team_id",
        "home_goals", "away_goals", "finished"])
    df["season"] = "2025-2026"
    for c in ("home_team_id", "away_team_id", "home_goals", "away_goals"):
        df[c] = df[c].astype("Int64")
    return df


def record(i: int, date: str, home: str, away: str, hs, as_, hb=1800.0, ha=1810.0,
           ab=1700.0, aa=1690.0, season: str = "2025-2026") -> dict:
    """One /matches record in the documented shape."""
    return {
        "id": i, "date": date, "competition": "test-pl", "season": season, "stage": None,
        "matchday": 1, "home": home, "away": away, "home_score": hs, "away_score": as_,
        "home_elo_before": hb, "home_elo_after": ha, "away_elo_before": ab, "away_elo_after": aa,
    }


def records() -> list[dict]:
    """beyondELO's view of the fixtures: m1-m3 played, m4 unplayed, plus one match we lack."""
    return [
        record(101, "2025-08-16", "Alpha", "Beta", 2, 1, 1800.5, 1805.5, 1700.0, 1695.0),
        record(102, "2025-08-16", "Gamma", "Delta", 0, 0, 1750.0, 1748.0, 1650.0, 1652.0),
        record(103, "2025-08-23", "Beta", "Gamma", 1, 3, 1695.0, 1690.0, 1748.0, 1752.0),
        record(104, "2025-08-30", "Delta", "Alpha", None, None, None, None, None, None),
        record(105, "2025-09-13", "Alpha", "Gamma", 1, 1),
    ]


def page(rows: list[dict], total: int, number: int = 1, per_page: int = 100) -> dict:
    """A /matches response body."""
    return {"data": rows, "meta": {"total": total, "page": number, "per_page": per_page}}


class FakeTransport:
    """A transport that answers from a queue (or a function) and records every call."""

    def __init__(self, responses=None, handler=None) -> None:
        self.responses = list(responses or [])
        self.handler = handler
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str], timeout: float):
        self.calls.append((url, dict(headers)))
        if self.handler is not None:
            return self.handler(url)
        return self.responses.pop(0)


def ok(body, headers: dict[str, str] | None = None):
    """A 200 response."""
    hdr = {"x-ratelimit-remaining": "99", "x-ratelimit-remaining-minute": "9"}
    hdr.update(headers or {})
    return 200, hdr, json.dumps(body).encode()


class FakeTime:
    """An injectable clock whose only movement is the sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def api_settings(tmp_path: Path, **kw) -> api.Settings:
    """Client settings with the cache under `tmp_path/raw`."""
    base = {"base_url": "https://example.test/v1", "per_page": 100, "max_requests": 20,
            "min_seconds": 6.5, "timeout": 5, "raw_dir": tmp_path / "raw"}
    base.update(kw)
    return api.Settings(**base)


def api_client(tmp_path: Path, transport, env=None, ft=None, **kw) -> api.Client:
    """A client on a fake transport and clock; the key is set unless `env` says otherwise."""
    ft = ft or FakeTime()
    env = {"BEYONDELO_API_KEY": KEY} if env is None else env
    return api.Client(api_settings(tmp_path, **kw), transport, ft.clock, ft.sleep, env)


def comps() -> dict:
    """The invented /competitions response."""
    return json.loads((FIXTURES / "competitions.json").read_text())
