"""Polite, safe HTTP fetching shared by connectors.

* SSRF guard on every URL (openquyhoach_core.security.check_url_allowed)
* conditional requests via ETag / If-Modified-Since
* streaming download with hard byte cap
* exponential backoff on 429/5xx via tenacity
* identifiable, configurable User-Agent
* per-source crawl delay
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from openquyhoach_core.errors import FetchBlockedError
from openquyhoach_core.hashing import sha256_file
from openquyhoach_core.logging import get_logger
from openquyhoach_core.security import check_url_allowed
from openquyhoach_core.settings import get_settings
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = get_logger(__name__)

_last_hit: dict[str, float] = {}


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
) -> dict:
    """Download `url` to `dest_dir`, honouring cache validators.

    Returns dict with local_path/sha256/size/mime/etag/last_modified/
    retrieved_url/not_modified. Raises FetchBlockedError for policy denials,
    httpx.HTTPError for transport failures.
    """
    s = get_settings()
    check_url_allowed(url, s)
    host = urlparse(url).hostname or ""
    _respect_delay(host, float(crawl_delay))

    headers = {"User-Agent": s.fetch_user_agent, "Accept": "*/*"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    limit = max_bytes or s.fetch_max_bytes
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed via `with tmp` below
        dir=dest_dir, delete=False, prefix="dl-"
    )
    tmp_path = Path(tmp.name)
    total = 0
    try:
        with httpx.stream(
            "GET",
            url,
            headers=headers,
            follow_redirects=True,
            timeout=s.fetch_timeout_seconds,
        ) as resp:
            if resp.status_code == 304:
                return {"not_modified": True, "url": url}
            if resp.status_code in (429, 500, 502, 503, 504):
                raise RetryableFetch(f"HTTP {resp.status_code} for {url}")
            resp.raise_for_status()
            # Re-check the *final* URL after redirects — a public URL may
            # redirect to a private host.
            check_url_allowed(str(resp.url), s)
            cl = resp.headers.get("content-length")
            if cl and int(cl) > limit:
                raise FetchBlockedError(
                    f"content-length {cl} exceeds cap {limit}", detail={"url": url}
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
            return {
                "not_modified": False,
                "local_path": tmp_path,
                "canonical_url": url,
                "retrieved_url": str(resp.url),
                "sha256": sha,
                "size": size,
                "mime_type": (resp.headers.get("content-type") or "").split(";")[0] or None,
                "etag": resp.headers.get("etag"),
                "last_modified": resp.headers.get("last-modified"),
            }
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
