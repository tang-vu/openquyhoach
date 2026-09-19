"""robots.txt honouring — cached per origin.

Crawlers consult ``robots_allowed`` before fetching when a source's
``crawl_policy.respect_robots`` is true (the default). The file is fetched
with our own client so the SSRF guard, UA and timeout apply.

Status handling follows RFC 9309 §2.3.1:

* 2xx      → parse rules
* 404/4xx  → no restrictions (allow all), except 401/403 → disallow all
* 5xx      → temporary unavailability → disallow (we suspend politely)
* transport errors → treat as unavailable (disallow) — never hammer a
  failing host
"""

from __future__ import annotations

import time
import urllib.robotparser
from urllib.parse import urlparse

import httpx

from .logging import get_logger
from .settings import Settings, get_settings

log = get_logger(__name__)

# origin -> (expires_epoch, rules) where rules is None for "no file" and a
# parsed RobotFileParser otherwise. Re-read at most once per TTL/process.
_cache: dict[str, tuple[float, urllib.robotparser.RobotFileParser | None]] = {}
_TTL = 3600.0


def _origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _deny_all() -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(["User-agent: *", "Disallow: /"])
    return rp


def _load_parser(
    origin: str, settings: Settings, verify_tls: bool = True
) -> urllib.robotparser.RobotFileParser | None:
    now = time.monotonic()
    cache_key = (origin, verify_tls)
    cached = _cache.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]
    parser: urllib.robotparser.RobotFileParser | None
    resp: httpx.Response | None = None
    for attempt in range(3):
        try:
            resp = httpx.get(
                f"{origin}/robots.txt",
                headers={"User-Agent": settings.fetch_user_agent},
                timeout=settings.fetch_timeout_seconds,
                follow_redirects=True,
                verify=verify_tls,
            )
            break
        except Exception as exc:
            log.info(
                "robots.fetch_retry",
                origin=origin,
                attempt=attempt,
                error=str(exc)[:160],
            )
            time.sleep(1.0 + attempt)
    if resp is not None:
        status = resp.status_code
        if status in (401, 403) or status >= 500:
            parser = _deny_all()
        elif status >= 400:
            parser = None  # 404/410/other 4xx: no rules
        else:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(f"{origin}/robots.txt")
            try:
                rp.parse(resp.text.splitlines())
                parser = rp
            except Exception:
                parser = None
    else:
        parser = _deny_all()
    _cache[cache_key] = (now + _TTL, parser)
    return parser


def robots_allowed(
    url: str,
    settings: Settings | None = None,
    user_agent: str | None = None,
    verify_tls: bool = True,
) -> bool:
    """True when robots.txt permits ``user_agent`` to fetch ``url``.

    file:// resources have no robots semantics. A parsed ruleset is the
    only source of truth — never a guess.
    """
    s = settings or get_settings()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return True
    parser = _load_parser(_origin(url), s, verify_tls)
    if parser is None:
        return True
    try:
        return bool(parser.can_fetch(user_agent or s.fetch_user_agent, url))
    except Exception:
        return False


def crawl_delay(
    url: str,
    settings: Settings | None = None,
    user_agent: str | None = None,
    verify_tls: bool = True,
) -> float | None:
    """Server-declared crawl-delay for this origin, if any."""
    s = settings or get_settings()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    parser = _load_parser(_origin(url), s, verify_tls)
    if parser is None:
        return None
    try:
        d = parser.crawl_delay(user_agent or s.fetch_user_agent)
        return float(d) if d is not None else None
    except Exception:
        return None


def reset_cache() -> None:
    """Test hook: drop cached parsers."""
    _cache.clear()
