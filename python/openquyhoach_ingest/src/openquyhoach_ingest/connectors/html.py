"""Generic HTML index/detail-page connector.

Discovery parses a listing page with configurable selectors:

    discovery:
      index_url: https://example.gov.vn/van-ban
      link_selector: "a.doc-link"        # CSS selector for detail/file links
      attr: href                          # attribute holding the URL (default href)
      detail:                             # optional second hop
        enabled: true
        file_selector: "a.download"
      field_selectors:                    # metadata scraped off the row/element
        title: "span.title"
        date: "span.date"

No CAPTCHA/auth bypass — pages must be publicly fetchable.
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


class HtmlConnector:
    source_type = "html_index"

    def _get_html(self, url: str, delay: float) -> BeautifulSoup:
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
        delay = float(source.crawl_policy.get("delay_seconds", 1.0))
        soup = self._get_html(index_url, delay)
        link_sel = d.get("link_selector", "a")
        attr = d.get("attr", "href")
        field_selectors = d.get("field_selectors") or {}
        detail = d.get("detail") or {}
        allowed = set(source.allowed_formats or [])

        for el in soup.select(link_sel):
            href = el.get(attr)
            if isinstance(href, list):
                href = href[0] if href else None
            if not href:
                continue
            url = urljoin(index_url, str(href))
            meta = {}
            for field_name, sel in field_selectors.items():
                sub = el.select_one(sel)
                if sub is not None:
                    meta[field_name] = sub.get_text(strip=True)
            if detail.get("enabled"):
                detail_soup = self._get_html(url, delay)
                file_sel = detail.get("file_selector", "a")
                fe = detail_soup.select_one(file_sel)
                fe_href = fe.get("href") if fe else None
                if isinstance(fe_href, list):
                    fe_href = fe_href[0] if fe_href else None
                if fe is None or not fe_href:
                    continue
                url = urljoin(url, str(fe_href))
            if allowed and not any(url.lower().endswith(f".{ext}") for ext in allowed):
                continue
            yield DiscoveredItem(
                url=url,
                suggested_filename=url.rsplit("/", 1)[-1] or None,
                metadata=meta,
            )

    def fetch(self, source: SourceConfig, item: DiscoveredItem, workdir: Path) -> FetchResult:
        res = fetch_url(
            item.url,
            workdir,
            etag=item.etag,
            last_modified=item.last_modified,
            crawl_delay=float(source.crawl_policy.get("delay_seconds", 1.0)),
            max_bytes=(source.rate_limit or {}).get("max_bytes"),
            user_agent=source.crawl_policy.get("user_agent"),
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


register(HtmlConnector())
