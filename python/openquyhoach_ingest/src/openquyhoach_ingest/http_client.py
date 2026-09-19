"""Polite, safe HTTP fetching shared by connectors.

* SSRF guard on every URL (openquyhoach_core.security.check_url_allowed),
  re-validated on *each* redirect hop before it is followed
* conditional requests via ETag / If-Modified-Since
* streaming download with hard byte cap
* exponential backoff on 429/5xx via tenacity
* identifiable, configurable User-Agent (per-source override allowed)
* per-host crawl delay (descriptor + robots.txt crawl-delay, larger wins)
* Content-Disposition filename extraction
* optional expected-sha256 verification
* selected response headers preserved for provenance
"""

from __future__ import annotations

import re
import tempfile
import time
from email.message import Message
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx
from openquyhoach_core.errors import FetchBlockedError, ValidationError
from openquyhoach_core.hashing import sha256_file
from openquyhoach_core.logging import get_logger
from openquyhoach_core.robots import crawl_delay as robots_crawl_delay
from openquyhoach_core.security import check_url_allowed
from openquyhoach_core.settings import get_settings
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = get_logger(__name__)

_last_hit: dict[str, float] = {}

# Redirects are followed manually so every hop can be re-validated.
_MAX_REDIRECTS = 10

# Headers worth keeping as fetch evidence — never credentials or cookies.
_CAPTURED_HEADERS = (
    "content-type",
    "content-length",
    "content-disposition",
    "etag",
    "last-modified",
    "cache-control",
    "expires",
    "server",
)


class RetryableFetch(Exception):
    pass


def _respect_delay(host: str, delay: float) -> None:
    if delay <= 0:
        return
    last = _last_hit.get(host)
    if last is not None:
        wait = delay - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
    _last_hit[host] = time.monotonic()


def filename_from_headers(content_disposition: str | None, url: str) -> str | None:
    """Best filename for a response: Content-Disposition > URL path."""
    if content_disposition:
        msg = Message()
        msg["content-disposition"] = content_disposition
        name = msg.get_filename()
        if name:
            return unquote(str(name)).rsplit("/", 1)[-1] or None
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', content_disposition, re.I)
        if m:
            return unquote(m.group(1)).rsplit("/", 1)[-1] or None
    path_name = Path(unquote(urlparse(url).path)).name
    return path_name or None


@retry(
    retry=retry_if_exception_type(RetryableFetch),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    stop=stop_after_attempt(4),
    reraise=True,
)
def fetch_url(
    url: str,
    dest_dir: Path,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    crawl_delay: float = 0.0,
    max_bytes: int | None = None,
    expected_sha256: str | None = None,
    user_agent: str | None = None,
    extra_headers: dict[str, str] | None = None,
    verify_tls: bool = True,
) -> dict:
    """Download `url` to `dest_dir`, honouring cache validators.

    Returns dict with local_path/sha256/size/mime/etag/last_modified/
    retrieved_url/not_modified/filename/response_headers. Raises
    FetchBlockedError for policy denials, httpx.HTTPError for transport
    failures, ValidationError when expected_sha256 mismatches.
    """
    s = get_settings()
    check_url_allowed(url, s)
    host = urlparse(url).hostname or ""
    # effective delay: descriptor value vs robots.txt crawl-delay — larger wins
    declared = robots_crawl_delay(url, s, user_agent, verify_tls)
    delay = max(float(crawl_delay), declared or 0.0)
    _respect_delay(host, delay)

    headers = {"User-Agent": user_agent or s.fetch_user_agent, "Accept": "*/*"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    if extra_headers:
        headers.update(extra_headers)

    limit = max_bytes or s.fetch_max_bytes
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed via `with tmp` below
        dir=dest_dir, delete=False, prefix="dl-"
    )
    tmp_path = Path(tmp.name)
    total = 0
    try:
        current = url
        # Manual redirect following: every hop is re-validated against the
        # SSRF guard *before* it is requested — a public URL redirecting to
        # a private/metadata host is refused without issuing the request.
        for _hop in range(_MAX_REDIRECTS + 1):
            check_url_allowed(current, s)
            with httpx.stream(
                "GET",
                current,
                headers=headers,
                follow_redirects=False,
                timeout=s.fetch_timeout_seconds,
                verify=verify_tls,
            ) as resp:
                if resp.is_redirect and resp.headers.get("location"):
                    current = urljoin(current, resp.headers["location"])
                    continue
                if resp.status_code == 304:
                    return {"not_modified": True, "url": url, "http_status": 304}
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise RetryableFetch(f"HTTP {resp.status_code} for {url}")
                resp.raise_for_status()
                cl = resp.headers.get("content-length")
                if cl and cl.isdigit() and int(cl) > limit:
                    raise FetchBlockedError(
                        f"content-length {cl} exceeds cap {limit}",
                        detail={"url": url},
                    )
                with tmp:
                    for chunk in resp.iter_bytes(1024 * 256):
                        total += len(chunk)
                        if total > limit:
                            raise FetchBlockedError(
                                f"download exceeds cap {limit}", detail={"url": url}
                            )
                        tmp.write(chunk)
                sha, size = sha256_file(tmp_path)
                if expected_sha256 and sha != expected_sha256:
                    raise ValidationError(
                        f"checksum mismatch: expected {expected_sha256}, got {sha}",
                        detail={"url": url},
                    )
                resp_headers = {
                    h: resp.headers[h]
                    for h in _CAPTURED_HEADERS
                    if h in resp.headers
                }
                return {
                    "not_modified": False,
                    "local_path": tmp_path,
                    "canonical_url": url,
                    "retrieved_url": str(resp.url),
                    "http_status": resp.status_code,
                    "sha256": sha,
                    "size": size,
                    "mime_type": (resp.headers.get("content-type") or "").split(";")[0]
                    or None,
                    "etag": resp.headers.get("etag"),
                    "last_modified": resp.headers.get("last-modified"),
                    "filename": filename_from_headers(
                        resp.headers.get("content-disposition"), str(resp.url)
                    ),
                    "response_headers": resp_headers,
                }
        else:
            raise FetchBlockedError(
                f"too many redirects for {url}", detail={"url": url}
            )
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
