"""beyondELO's HTTP API: a budgeted, cached, key-safe client and the pull of Premier League matches.

The key is read from the environment variable BEYONDELO_API_KEY at the moment of a request, goes
only in the X-API-Key header, and is never stored, logged or put in a message. Standard library
only. Every response is cached as raw JSON before it is checked, so a cached response is never
requested again and a build can be re-run from the cache with no key and no request.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

KEY_VAR = "BEYONDELO_API_KEY"

# (url, headers, timeout seconds) -> (status, lower-cased response headers, body)
Transport = Callable[[str, dict[str, str], float], tuple[int, dict[str, str], bytes]]


class BeyondEloError(RuntimeError):
    """The pull cannot go on: no key, a spent budget, a bad status or an unexpected response."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would resend the key header to wherever it points."""

    def redirect_request(
        self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def urllib_transport(
    url: str, headers: dict[str, str], timeout: float
) -> tuple[int, dict[str, str], bytes]:
    """One GET through urllib. A non-2xx status is returned, not raised."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read(2000) if exc.fp is not None else b""
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, body
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise BeyondEloError(f"request failed before any response: {reason}") from None


@dataclass(frozen=True)
class Settings:
    """The `beyondelo:` config the client needs."""

    base_url: str
    per_page: int
    max_requests: int
    min_seconds: float
    timeout: float
    raw_dir: Path

    def check(self) -> None:
        """Refuse a base URL that is not https, so the key is never sent in clear."""
        if not self.base_url.startswith("https://"):
            raise BeyondEloError("beyondelo base_url must be https")


class Client:
    """GET JSON from beyondELO within a request budget, with a file cache."""

    def __init__(
        self,
        settings: Settings,
        transport: Transport = urllib_transport,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        settings.check()
        self.settings = settings
        self._transport = transport
        self._clock = clock
        self._sleep = sleep
        self._environ = os.environ if environ is None else environ
        self.requests_made = 0
        self._last: float | None = None

    def __repr__(self) -> str:
        return f"Client(requests_made={self.requests_made})"

    def _key(self) -> str:
        key = (self._environ.get(KEY_VAR) or "").strip()
        if not key:
            raise BeyondEloError(f"set the environment variable {KEY_VAR} to make a request")
        return key

    def _pace(self) -> None:
        if self._last is not None:
            wait = self.settings.min_seconds - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def get_json(self, endpoint: str, params: dict[str, Any], cache_name: str) -> Any:
        """The JSON at `endpoint`, from the cache if saved, else requested once and saved."""
        path = self.settings.raw_dir / cache_name
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                raise BeyondEloError(f"{path} is not valid JSON: delete it to re-pull") from None
        if self.remaining <= 0:
            raise BeyondEloError(
                f"request cap of {self.settings.max_requests} reached; about 9 requests are "
                f"expected, so something is wrong: check the cached responses in "
                f"{self.settings.raw_dir} before re-running"
            )
        key = self._key()
        headers = {"X-API-Key": key, "Accept": "application/json", "User-Agent": "fpl-model"}
        self._pace()
        query = urllib.parse.urlencode(sorted(params.items()))
        url = f"{self.settings.base_url}{endpoint}" + (f"?{query}" if query else "")
        self.requests_made += 1
        status, resp_headers, body = self._transport(url, headers, self.settings.timeout)
        self._log_limits(endpoint, status, resp_headers)
        if status != 200:
            if status not in (401, 403):  # an auth failure's body is never logged
                text = _redact(body.decode("utf-8", "replace"), key)
                log.warning("response body: %s", text[:300])
            wait = resp_headers.get("retry-after")
            retry = f" (Retry-After {wait} s)" if wait else ""
            msg = f"GET {endpoint} returned HTTP {status}{retry}; stopping, no retry"
            raise BeyondEloError(msg)
        try:
            data = json.loads(body)
        except ValueError:
            raise BeyondEloError(f"GET {endpoint} returned a body that is not JSON") from None
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(path)
        return data

    @property
    def remaining(self) -> int:
        """Requests left in this run's budget."""
        return self.settings.max_requests - self.requests_made

    def _log_limits(self, endpoint: str, status: int, headers: dict[str, str]) -> None:
        log.info(
            "request %d/%d GET %s -> %s; %s left today, %s this minute",
            self.requests_made, self.settings.max_requests, endpoint, status,
            headers.get("x-ratelimit-remaining", "?"),
            headers.get("x-ratelimit-remaining-minute", "?"),
        )


def _redact(text: str, key: str) -> str:
    """`text` with the key, in the forms a server might echo it, replaced by `***`."""
    forms = {key, urllib.parse.quote(key, safe=""), urllib.parse.quote_plus(key),
             key.replace("/", "\\/")}
    for form in sorted(forms, key=len, reverse=True):
        text = text.replace(form, "***")
    return text


def _records(payload: Any, what: str) -> list[dict]:
    """The list of records under `data` in a response."""
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise BeyondEloError(f"{what}: expected a list of records under `data`")
    return rows


def find_premier_league_code(competitions: list[dict]) -> str:
    """The code of the one English domestic league in /competitions; none or several is an error."""
    codes = [
        c.get("code") for c in competitions
        if str(c.get("country") or "").strip().lower() == "england"
        and c.get("tier") == "domestic_league"
    ]
    if len(codes) != 1 or not codes[0]:
        raise BeyondEloError(
            "cannot identify the Premier League in /competitions "
            f"(England, domestic_league): found {codes}"
        )
    return str(codes[0])


def fetch_matches(client: Client, code: str, season: str, max_total: int) -> list[dict]:
    """Every match of one competition-season, paging until `meta.total` is covered.

    Stops after page 1 if `meta.total` exceeds `max_total` (the Premier League fixtures we hold),
    if the pages it implies exceed the requests left, or if a record is from another season
    (each means the filters were ignored). Only `season` is checked: whether a record's
    `competition` holds a code or a name is not known until the first real response.
    To refresh a season, delete `raw/matches_{season}_p*.json`.
    """
    per_page, out, pages, number = client.settings.per_page, [], 1, 1
    while number <= pages:
        name = f"matches_{season}_p{number}.json"
        params = {"competition": code, "season": season, "page": number, "per_page": per_page}
        payload = client.get_json("/matches", params, name)
        meta = payload.get("meta") if isinstance(payload, dict) else None
        total = meta.get("total") if isinstance(meta, dict) else None
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise BeyondEloError(f"{name}: no usable meta.total")
        if meta.get("page", number) != number:
            raise BeyondEloError(f"{name}: asked for page {number}, got page {meta['page']}")
        rows = _records(payload, name)
        other = sorted({str(r.get("season")) for r in rows} - {season})
        if other:
            raise BeyondEloError(f"{name}: asked for {season} but got seasons {other}; "
                                 f"delete matches_{season}_p*.json before re-running")
        out += rows
        pages = math.ceil(total / (meta.get("per_page") or per_page))
        if number == 1 and total > max_total:
            raise BeyondEloError(
                f"{name}: total {total} is more than the {max_total} Premier League fixtures we "
                f"hold: the filters may have been ignored; check the file before re-running")
        if number == 1 and pages - 1 > client.remaining:
            raise BeyondEloError(
                f"{name}: total {total} implies {pages} pages but only {client.remaining} "
                f"requests are left: the filters may have been ignored; check the file "
                f"before re-running")
        number += 1
    if len(out) != total:
        raise BeyondEloError(f"matches {season}: {len(out)} rows read but meta.total is {total}")
    log.info("matches %s: %d rows over %d page(s)", season, total, max(pages, 1))
    return out


def pull(client: Client, max_totals: dict[str, int]) -> dict[str, list[dict]]:
    """Confirm the Premier League's code from /competitions, then fetch each season's matches.

    `max_totals` maps each season to the Premier League fixtures we hold for it.
    """
    comps = _records(client.get_json("/competitions", {}, "competitions.json"), "competitions")
    code = find_premier_league_code(comps)
    log.info("Premier League competition code: %s", code)
    return {season: fetch_matches(client, code, season, n) for season, n in max_totals.items()}
