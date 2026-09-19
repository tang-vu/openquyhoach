"""Vietnamese national planning-portal connector (conservative).

The national planning information portal exposes a public listing UI. We
consume only pages/files reachable anonymously, honour crawl-delay, and keep
this connector isolated so upstream markup changes degrade to a descriptor
update, not a code change.

Everything is selector-driven in the source descriptor — this connector just
implements the detail-page → attachment flow on top of the HTML machinery.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from openquyhoach_core.security import check_url_allowed
from openquyhoach_core.settings import get_settings

from ..http_client import fetch_url
from .base import DiscoveredItem, FetchResult, SourceConfig, register


class PlanningPortalConnector:
    source_type = "planning_portal"

    def _soup(self, url: str) -> BeautifulSoup:
        s = get_settings()
        check_url_allowed(url, s)
        with httpx.Client(
            headers={"User-Agent": s.fetch_user_agent},
            timeout=s.fetch_timeout_seconds,
            follow_redirects=True,
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")

    def discover(self, source: SourceConfig) -> Iterable[DiscoveredItem]:
        d = source.discovery
        index_url = d.get("index_url") or source.base_url
        if not index_url:
            return
        page_param = d.get("page_param", "page")
        max_pages = int(d.get("max_pages", 3))  # conservative default
        item_sel = d.get("item_selector", "a")
        attach_sel = d.get("attachment_selector", "a[href$='.pdf'], a[href$='.zip']")
        field_selectors = d.get("field_selectors") or {}
        allowed = set(source.allowed_formats or [])

        for page in range(1, max_pages + 1):
            sep = "&" if "?" in index_url else "?"
            soup = self._soup(f"{index_url}{sep}{page_param}={page}")
            items = soup.select(item_sel)
            if not items:
                break
            for el in items:
                href = el.get("href")
                if isinstance(href, list):
                    href = href[0] if href else None
                if not href:
                    continue
                detail_url = urljoin(index_url, str(href))
                meta = {
                    n: (
                        sel.get_text(strip=True)
                        if (sel := el.select_one(s)) is not None
                        else None
                    )
                    for n, s in field_selectors.items()
                }
                detail = self._soup(detail_url)
                for a in detail.select(attach_sel):
                    a_href = a.get("href", "")
                    if isinstance(a_href, list):
                        a_href = a_href[0] if a_href else ""
                    file_url = urljoin(detail_url, str(a_href))
                    if allowed and not any(
                        file_url.lower().split("?")[0].endswith(f".{ext}") for ext in allowed
                    ):
                        continue
                    yield DiscoveredItem(
                        url=file_url,
                        suggested_filename=file_url.rsplit("/", 1)[-1].split("?")[0],
                        metadata={**meta, "detail_url": detail_url},
                    )

    def fetch(self, source: SourceConfig, item: DiscoveredItem, workdir: Path) -> FetchResult:
        res = fetch_url(
            item.url,
            workdir,
            etag=item.etag,
            last_modified=item.last_modified,
            crawl_delay=float(source.crawl_policy.get("delay_seconds", 2.0)),
            max_bytes=(source.rate_limit or {}).get("max_bytes"),
            user_agent=source.crawl_policy.get("user_agent"),
            verify_tls=bool(source.crawl_policy.get("verify_tls", True)),
        )
        if res.get("not_modified"):
            return FetchResult(
                local_path=Path(""),
                canonical_url=item.url,
                retrieved_url=item.url,
                sha256="",
                size=0,
                not_modified=True,
                http_status=res.get("http_status"),
            )
        return FetchResult(
            local_path=res["local_path"],
            canonical_url=res["canonical_url"],
            retrieved_url=res["retrieved_url"],
            sha256=res["sha256"],
            size=res["size"],
            mime_type=res.get("mime_type"),
            etag=res.get("etag"),
            last_modified=res.get("last_modified"),
            filename=res.get("filename"),
            http_status=res.get("http_status"),
            response_headers=res.get("response_headers") or {},
        )

    def inspect(self, result: FetchResult) -> dict:
        from openquyhoach_core.security import sniff_format

        head = result.local_path.read_bytes()[:512]
        return {"detected_format": sniff_format(head, result.local_path.name)}


register(PlanningPortalConnector())
