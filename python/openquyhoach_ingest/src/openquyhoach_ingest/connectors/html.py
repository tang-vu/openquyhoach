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
from .common import _patterns


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

    def _pages(self, index_url: str, d: dict, delay: float) -> Iterable[tuple[str, BeautifulSoup]]:
        """Yield (page_url, soup) — single page, or paginated when
        ``discovery.pagination`` is configured. Schema styles:

        * ``next_link``: ``next_selector`` CSS for the next-page link,
          followed until absent or ``max_pages``.
        * ``param``: ``?{param}=N`` (or ``page_param`` shorthand) iterated
          from ``start`` until a page has no candidate links.
        * ``path``: ``path_template`` like ``/van-ban/page/{page}``.
        """
        pag = d.get("pagination") or {}
        style = pag.get("style")
        next_sel = pag.get("next_selector")
        page_param = pag.get("param") or d.get("page_param")
        path_template = pag.get("path_template")
        if not style:
            style = "next_link" if next_sel else ("param" if page_param else ("path" if path_template else None))
        if not style:
            yield index_url, self._get_html(index_url, delay)
            return
        link_sel = d.get("link_selector", "a")
        max_pages = int(pag.get("max_pages") or d.get("max_pages") or 50)
        start = int(pag.get("start") or 1)
        if style == "next_link":
            url: str | None = index_url
            seen: set[str] = set()
            pages = 0
            while url and pages < max_pages and url not in seen:
                seen.add(url)
                pages += 1
                soup = self._get_html(url, delay)
                yield url, soup
                nxt = soup.select_one(next_sel) if next_sel else None
                href = nxt.get("href") if nxt else None
                url = urljoin(url, href) if href else None
            return
        from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

        for n in range(start, start + max_pages):
            if style == "path" and path_template:
                url = urljoin(index_url, path_template.replace("{page}", str(n)))
            else:
                parts = urlparse(index_url)
                q = dict(parse_qsl(parts.query))
                q[page_param or "page"] = str(n)
                url = urlunparse(parts._replace(query=urlencode(q)))
            soup = self._get_html(url, delay)
            yield url, soup
            if not soup.select(link_sel):
                break  # empty page — stop paginating

    def discover(self, source: SourceConfig) -> Iterable[DiscoveredItem]:
        import re

        d = source.discovery
        index_url = d.get("index_url") or source.base_url
        if not index_url:
            return
        delay = float(source.crawl_policy.get("delay_seconds", 1.0))
        link_sel = d.get("link_selector", "a")
        attr = d.get("attr", "href")
        field_selectors = d.get("field_selectors") or {}
        detail = d.get("detail") or d.get("follow") or {}
        allowed = set(source.allowed_formats or [])
        include = [re.compile(p) for p in _patterns(d, "include", "url_include")]
        exclude = [re.compile(p) for p in _patterns(d, "exclude", "url_exclude")]
        max_items = int(d.get("max_resources") or 5000)
        seen_urls: set[str] = set()
        emitted = 0

        for page_url, soup in self._pages(index_url, d, delay):
            for el in soup.select(link_sel):
                if emitted >= max_items:
                    return
                href = el.get(attr)
                if isinstance(href, list):
                    href = href[0] if href else None
                if not href:
                    continue
                url = urljoin(page_url, str(href))
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
                if include and not any(p.search(url) for p in include):
                    continue
                if any(p.search(url) for p in exclude):
                    continue
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                emitted += 1
                yield DiscoveredItem(
                    url=url,
                    suggested_filename=url.rsplit("/", 1)[-1] or None,
                    metadata={**meta, "page_url": page_url},
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
