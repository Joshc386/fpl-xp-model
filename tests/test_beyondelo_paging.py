"""beyondELO pull: competition code, paging, and the two guards against an ignored filter."""

from __future__ import annotations

import pytest

import beyondelo_helpers as h
from beyondelo_helpers import api_client as client
from beyondelo_helpers import comps
from fpl import beyondelo_api as api


def pull(c: api.Client, seasons: list[str], n: int = 1000) -> dict[str, list[dict]]:
    """api.pull with `n` Premier League fixtures held for each season."""
    return api.pull(c, {s: n for s in seasons})


# --- competition code -------------------------------------------------------------------

def test_premier_league_code_found():
    assert api.find_premier_league_code(comps()["data"]) == "test-pl"


@pytest.mark.parametrize("rows", [
    [],
    [{"code": "x", "country": "Spain", "tier": "domestic_league"}],
    [{"code": "c", "country": None, "tier": "continental_club"}],
    [{"code": "e", "country": "England", "tier": "continental_club"}],
    [{"code": "a", "country": "England", "tier": "domestic_league"},
     {"code": "b", "country": "England", "tier": "domestic_league"}],
])
def test_premier_league_code_missing_or_ambiguous(rows):
    with pytest.raises(api.BeyondEloError, match="Premier League"):
        api.find_premier_league_code(rows)


def test_country_must_be_spelled_england():
    with pytest.raises(api.BeyondEloError, match="Premier League"):
        api.find_premier_league_code([{"code": "x", "country": "ENG", "tier": "domestic_league"}])


def test_bare_list_responses_are_refused(tmp_path):
    t = h.FakeTransport([h.ok(comps()["data"])])
    with pytest.raises(api.BeyondEloError, match="under `data`"):
        pull(client(tmp_path, t), ["2025-2026"])


def test_bad_competition_code_stops_before_any_matches_request(tmp_path):
    body = {"data": [{"code": "x", "country": "Spain", "tier": "domestic_league"}]}
    t = h.FakeTransport([h.ok(body)])
    with pytest.raises(api.BeyondEloError, match="Premier League"):
        pull(client(tmp_path, t), ["2025-2026"])
    assert len(t.calls) == 1 and "/competitions" in t.calls[0][0]


# --- paging -----------------------------------------------------------------------------

def rows(n: int, start: int = 0, season: str = "2025-2026") -> list[dict]:
    return [h.record(start + i, "2025-08-16", "Alpha", "Beta", 1, 0, season=season)
            for i in range(n)]


def paged(total: int, per_page: int = 100):
    def handler(url: str):
        if "competitions" in url:
            return h.ok(comps())
        n = int(url.split("page=")[1].split("&")[0])
        lo = (n - 1) * per_page
        season = url.split("season=")[1].split("&")[0]
        return h.ok(h.page(rows(min(per_page, total - lo), lo, season), total, n, per_page))
    return handler


@pytest.mark.parametrize(("total", "pages"), [(250, 3), (200, 2), (100, 1), (1, 1)])
def test_paging_covers_total_exactly(tmp_path, total, pages):
    t = h.FakeTransport(handler=paged(total))
    out = pull(client(tmp_path, t), ["2025-2026"])
    assert len(out["2025-2026"]) == total
    assert len(t.calls) == 1 + pages
    assert len({r["id"] for r in out["2025-2026"]}) == total
    assert "competition=test-pl" in t.calls[1][0] and "season=2025-2026" in t.calls[1][0]
    assert "per_page=100" in t.calls[1][0]
    assert (tmp_path / "raw" / f"matches_2025-2026_p{pages}.json").exists()


def test_total_zero_makes_no_further_requests(tmp_path):
    t = h.FakeTransport(handler=paged(0))
    out = pull(client(tmp_path, t), ["2025-2026"])
    assert out == {"2025-2026": []} and len(t.calls) == 2


def test_rows_not_matching_total_fail(tmp_path):
    t = h.FakeTransport([h.ok(comps()), h.ok(h.page(rows(3), 5))])
    with pytest.raises(api.BeyondEloError, match="total"):
        pull(client(tmp_path, t), ["2025-2026"])


def test_page_number_mismatch_fails(tmp_path):
    t = h.FakeTransport(
        [h.ok(comps()), h.ok(h.page(rows(100), 150)), h.ok(h.page(rows(50), 150, 3))])
    with pytest.raises(api.BeyondEloError, match="page"):
        pull(client(tmp_path, t), ["2025-2026"])


@pytest.mark.parametrize("body", [{"nope": 1}, {"data": {}}, {"data": [], "meta": {}}, [1]])
def test_unexpected_matches_shape_fails(tmp_path, body):
    t = h.FakeTransport([h.ok(comps()), h.ok(body)])
    with pytest.raises(api.BeyondEloError):
        pull(client(tmp_path, t), ["2025-2026"])


def test_pull_from_cache_alone_makes_no_request(tmp_path):
    pull(client(tmp_path, h.FakeTransport(handler=paged(150))), ["2025-2026", "2026-2027"])
    t = h.FakeTransport()
    out = pull(client(tmp_path, t, env={}), ["2025-2026", "2026-2027"])
    assert t.calls == [] and len(out["2026-2027"]) == 150


def test_cap_message_says_to_check_the_cache(tmp_path):
    c = client(tmp_path, h.FakeTransport(handler=lambda url: h.ok({"data": []})), max_requests=1)
    c.get_json("/a", {}, "a.json")
    with pytest.raises(api.BeyondEloError, match="check the cached responses"):
        c.get_json("/b", {}, "b.json")


def test_pages_beyond_the_budget_stop_after_page_one_and_keep_the_cache(tmp_path):
    t = h.FakeTransport(handler=paged(250))
    with pytest.raises(api.BeyondEloError, match="3 pages but only 1 requests"):
        pull(client(tmp_path, t, max_requests=3), ["2025-2026"])
    assert len(t.calls) == 2
    t2 = h.FakeTransport(handler=paged(250))
    pull(client(tmp_path, t2), ["2025-2026"])
    assert len(t2.calls) == 2


def test_ignored_filters_cost_one_request_not_the_budget(tmp_path):
    t = h.FakeTransport(handler=paged(50_000))
    with pytest.raises(api.BeyondEloError, match="filters may have been ignored"):
        pull(client(tmp_path, t), ["2025-2026"], n=100_000)
    assert len(t.calls) == 2


def test_record_from_another_season_stops_after_page_one(tmp_path):
    bad = [h.record(1, "2024-08-16", "Alpha", "Beta", 1, 0, season="2024-2025")]
    t = h.FakeTransport([h.ok(comps()), h.ok(h.page(bad, 250)), h.ok(h.page([], 250, 2))])
    with pytest.raises(api.BeyondEloError, match=r"2024-2025.*matches_2025-2026_p\*\.json"):
        pull(client(tmp_path, t), ["2025-2026"])
    assert len(t.calls) == 2


def test_served_per_page_smaller_than_requested_still_covers_total(tmp_path):
    t = h.FakeTransport(handler=paged(120, per_page=50))
    out = pull(client(tmp_path, t), ["2025-2026"])
    assert len(out["2025-2026"]) == 120 and len(t.calls) == 4


def test_pages_left_exactly_equal_to_requests_left_passes(tmp_path):
    t = h.FakeTransport(handler=paged(250))
    out = pull(client(tmp_path, t, max_requests=4), ["2025-2026"])
    assert len(out["2025-2026"]) == 250 and len(t.calls) == 4


@pytest.mark.parametrize(("count", "passes"), [(380, True), (379, False)])
def test_total_above_our_fixture_count_stops_after_page_one(tmp_path, count, passes):
    t = h.FakeTransport(handler=paged(380))
    if passes:
        assert len(pull(client(tmp_path, t), ["2025-2026"], n=count)["2025-2026"]) == 380
        return
    with pytest.raises(api.BeyondEloError, match=r"380 .*379.*filters may have been ignored"):
        pull(client(tmp_path, t), ["2025-2026"], n=count)
    assert len(t.calls) == 2
