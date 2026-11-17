"""beyondELO client: key handling, request budget, pacing, cache, transport, error bodies."""

from __future__ import annotations

import io
import logging
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

import beyondelo_helpers as h
from beyondelo_helpers import api_client as client
from beyondelo_helpers import comps
from fpl import beyondelo_api as api

# --- key ---------------------------------------------------------------------------------

@pytest.mark.parametrize("env", [{}, {"BEYONDELO_API_KEY": ""}, {"BEYONDELO_API_KEY": "  "}])
def test_missing_key_stops_before_any_request(tmp_path, env):
    t = h.FakeTransport([h.ok(comps())])
    with pytest.raises(api.BeyondEloError, match="BEYONDELO_API_KEY"):
        client(tmp_path, t, env=env).get_json("/competitions", {}, "competitions.json")
    assert t.calls == []


def test_key_sent_only_as_header_and_never_logged(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    t = h.FakeTransport([h.ok(comps()), (500, {}, b"boom")])
    c = client(tmp_path, t)
    c.get_json("/competitions", {}, "competitions.json")
    with pytest.raises(api.BeyondEloError) as exc:
        c.get_json("/matches", {"season": "2025-2026"}, "m.json")
    assert t.calls[0][1] == {
        "X-API-Key": h.KEY, "Accept": "application/json", "User-Agent": "fpl-model"}
    assert all(h.KEY not in url for url, _ in t.calls)
    assert h.KEY not in str(exc.value) and h.KEY not in repr(exc.value)
    assert h.KEY not in caplog.text and h.KEY not in repr(c)
    assert not any(h.KEY in p.read_text() for p in (tmp_path / "raw").iterdir())


# --- budget, pacing, failures --------------------------------------------------------------

def test_cap_reached_stops_without_exceeding_it(tmp_path):
    t = h.FakeTransport(handler=lambda url: h.ok({"data": []}))
    c = client(tmp_path, t, max_requests=2)
    c.get_json("/a", {}, "a.json")
    c.get_json("/b", {}, "b.json")
    with pytest.raises(api.BeyondEloError, match="cap of 2"):
        c.get_json("/c", {}, "c.json")
    assert len(t.calls) == 2


def test_requests_are_paced(tmp_path):
    ft = h.FakeTime()
    t = h.FakeTransport(handler=lambda url: h.ok({"data": []}))
    c = client(tmp_path, t, ft=ft)
    for n in range(3):
        c.get_json("/a", {"n": n}, f"a{n}.json")
    assert ft.sleeps == [6.5, 6.5]
    ft.now += 100
    c.get_json("/a", {"n": 9}, "a9.json")
    assert ft.sleeps == [6.5, 6.5]


@pytest.mark.parametrize("status", [429, 401, 422, 500])
def test_non_200_stops_with_no_retry(tmp_path, status):
    t = h.FakeTransport([(status, {"retry-after": "42"}, b"{}"), h.ok({"data": []})])
    with pytest.raises(api.BeyondEloError, match=str(status)) as exc:
        client(tmp_path, t).get_json("/a", {}, "a.json")
    assert len(t.calls) == 1
    if status == 429:
        assert "42" in str(exc.value)
    assert not (tmp_path / "raw" / "a.json").exists()


def test_invalid_json_is_an_error(tmp_path):
    t = h.FakeTransport([(200, {}, b"<html>")])
    with pytest.raises(api.BeyondEloError, match="not JSON"):
        client(tmp_path, t).get_json("/a", {}, "a.json")


def test_rate_limit_headers_are_logged(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    t = h.FakeTransport([h.ok({"data": []}, {"x-ratelimit-remaining": "77"})])
    client(tmp_path, t).get_json("/a", {}, "a.json")
    assert "77 left today" in caplog.text


def test_cached_response_is_not_requested_and_needs_no_key(tmp_path):
    t = h.FakeTransport([h.ok(comps())])
    client(tmp_path, t).get_json("/competitions", {}, "competitions.json")
    t2 = h.FakeTransport()
    again = client(tmp_path, t2, env={}).get_json("/competitions", {}, "competitions.json")
    assert again == comps() and t2.calls == []


# --- transport ----------------------------------------------------------------------------

class _Resp:
    status = 200
    headers = {"X-RateLimit-Remaining": "5"}

    def read(self) -> bytes:
        return b"{}"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Opener:
    def __init__(self, result):
        self.result = result

    def open(self, req, timeout):
        assert req.full_url.startswith("https://")
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_urllib_transport_maps_responses(monkeypatch):
    monkeypatch.setattr(api, "_OPENER", _Opener(_Resp()))
    status, headers, body = api.urllib_transport("https://x.test/a", {"X-API-Key": "k"}, 5)
    assert (status, headers["x-ratelimit-remaining"], body) == (200, "5", b"{}")
    err = urllib.error.HTTPError("https://x.test/a", 429, "Too Many", {"Retry-After": "3"}, None)
    monkeypatch.setattr(api, "_OPENER", _Opener(err))
    assert api.urllib_transport("https://x.test/a", {}, 5)[:2] == (429, {"retry-after": "3"})


def test_urllib_transport_connection_error_has_no_key(monkeypatch):
    monkeypatch.setattr(api, "_OPENER", _Opener(urllib.error.URLError("dns failure")))
    with pytest.raises(api.BeyondEloError, match="dns failure") as exc:
        api.urllib_transport("https://x.test/a", {"X-API-Key": h.KEY}, 5)
    assert h.KEY not in str(exc.value)


def test_redirects_are_not_followed():
    handler = api._NoRedirect()
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://evil.test") is None


def test_plain_http_base_url_is_refused(tmp_path):
    with pytest.raises(api.BeyondEloError, match="https"):
        h.api_settings(tmp_path, base_url="http://example.test/v1").check()


def test_error_body_is_logged_with_the_key_redacted(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    body = f"bad request for {h.KEY} please fix".encode()
    t = h.FakeTransport([(400, {}, body)])
    with pytest.raises(api.BeyondEloError) as exc:
        client(tmp_path, t).get_json("/a", {}, "a.json")
    assert "bad request for *** please fix" in caplog.text
    assert h.KEY not in caplog.text and h.KEY not in str(exc.value)


def test_error_body_log_is_cut_at_300_characters(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    t = h.FakeTransport([(422, {}, b"x" * 1000)])
    with pytest.raises(api.BeyondEloError):
        client(tmp_path, t).get_json("/a", {}, "a.json")
    assert "x" * 300 in caplog.text and "x" * 301 not in caplog.text


def test_cache_write_is_atomic_and_corrupt_cache_names_the_file(tmp_path):
    t = h.FakeTransport([h.ok({"data": []})])
    client(tmp_path, t).get_json("/a", {}, "a.json")
    assert [p.name for p in (tmp_path / "raw").iterdir()] == ["a.json"]
    (tmp_path / "raw" / "a.json").write_text("{oops", encoding="utf-8")
    with pytest.raises(api.BeyondEloError, match=r"a\.json is not valid JSON"):
        client(tmp_path, h.FakeTransport()).get_json("/a", {}, "a.json")


ODD_KEY = "AbC+def/ghi=jk"


def odd_forms() -> list[str]:
    return [ODD_KEY, urllib.parse.quote(ODD_KEY, safe=""), urllib.parse.quote_plus(ODD_KEY),
            ODD_KEY.replace("/", "\\/")]


@pytest.mark.parametrize("form", odd_forms())
def test_every_encoded_form_of_the_key_is_redacted(tmp_path, caplog, form):
    caplog.set_level(logging.INFO)
    t = h.FakeTransport([(400, {}, f"rejected {form} sorry".encode())])
    with pytest.raises(api.BeyondEloError):
        client(tmp_path, t, env={"BEYONDELO_API_KEY": ODD_KEY}).get_json("/a", {}, "a.json")
    assert "rejected *** sorry" in caplog.text and form not in caplog.text


def test_key_straddling_the_300_character_cut_leaks_no_prefix(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    t = h.FakeTransport([(400, {}, ("x" * 297 + ODD_KEY + "tail").encode())])
    with pytest.raises(api.BeyondEloError):
        client(tmp_path, t, env={"BEYONDELO_API_KEY": ODD_KEY}).get_json("/a", {}, "a.json")
    assert "x" * 297 + "***" in caplog.text and "AbC" not in caplog.text


@pytest.mark.parametrize("status", [401, 403])
def test_no_body_is_logged_for_401_and_403(tmp_path, caplog, status):
    caplog.set_level(logging.DEBUG)
    t = h.FakeTransport([(status, {}, b"some echo of the credentials")])
    with pytest.raises(api.BeyondEloError, match=str(status)):
        client(tmp_path, t).get_json("/a", {}, "a.json")
    assert "echo" not in caplog.text and "response body" not in caplog.text


def test_failed_replace_leaves_no_cache_file(tmp_path, monkeypatch):
    def boom(self, target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", boom)
    t = h.FakeTransport([h.ok({"data": []})])
    with pytest.raises(OSError, match="disk full"):
        client(tmp_path, t).get_json("/a", {}, "a.json")
    assert not (tmp_path / "raw" / "a.json").exists()


def test_urllib_transport_reads_the_body_of_an_http_error(monkeypatch):
    err = urllib.error.HTTPError(
        "https://x.test/a", 422, "Unprocessable", {"Retry-After": "3"}, io.BytesIO(b"bad filter"))
    monkeypatch.setattr(api, "_OPENER", _Opener(err))
    assert api.urllib_transport("https://x.test/a", {}, 5) == (
        422, {"retry-after": "3"}, b"bad filter")
