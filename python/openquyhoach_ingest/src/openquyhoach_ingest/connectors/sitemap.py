"""Sitemap connector — sitemap.xml / sitemap-index discovery.

Descriptor::

    source_type: sitemap
    base_url: https://example.gov.vn        # sitemap resolved via robots.txt
    discovery:
      sitemap_url: https://example.gov.vn/sitemap_index.xml   # optional
      url_include: ["quy-hoach", "\\.pdf$"]                   # regex, any match
      url_exclude: ["tag/", "page/"]
      max_sitemaps: 100
      max_urls: 20000

The robots.txt ``Sitemap:`` directive is honoured; a bare ``/sitemap.xml``
is the fallback. Sitemap indexes recurse (bounded).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlparse

from ..http_client import filename_from_headers
from .base import DiscoveredItem, FetchResult, SourceConfig, register
from .common import _patterns, get_text, get_xml
from .http import HttpConnector

_http = HttpConnector()


class SitemapConnector:
    source_type = "sitemap"

    # -- discovery ------------------------------------------------------

    def _sitemap_urls(self, source: SourceConfig) -> list[str]:
        d = source.discovery
        if d.get("sitemap_url"):
            return [d["sitemap_url"]]
        if d.get("sitemap_urls"):
            return list(d["sitemap_urls"])
        base = (source.base_url or "").rstrip("/")
        if not base:
            return []
        origin = f"{urlparse(base).scheme}://{urlparse(base).netloc}"
        found: list[str] = []
        try:
            robots = get_text(f"{origin}/robots.txt")
            for line in robots.splitlines():
                if line.lower().startswith("sitemap:"):
                    found.append(line.split(":", 1)[1].strip())
        except Exception:
            pass  # robots.txt optional — fall back to the conventional path
        return found or [f"{origin}/sitemap.xml"]

    def _walk(self, url: str, seen: set[str], budget: list[int]) -> Iterable[tuple[str, str | None]]:
        if url in seen or budget[0] <= 0:
            return
        seen.add(url)
        budget[0] -= 1
        try:
            root = get_xml(url)
        except Exception:
            return
        tag = root.tag.rsplit("}", 1)[-1]
        if tag == "sitemapindex":
            for sm in root:
                loc = next(
                    (c.text for c in sm if c.tag.rsplit("}", 1)[-1] == "loc"), None
                )
                if loc:
                    yield from self._walk(loc.strip(), seen, budget)
        elif tag == "urlset":
            for u in root:
                loc = lastmod = None
                for c in u:
                    t = c.tag.rsplit("}", 1)[-1]
                    if t == "loc":
                        loc = c.text
                    elif t == "lastmod":
                        lastmod = c.text
                if loc:
                    yield loc.strip(), (lastmod or "").strip() or None

    def discover(self, source: SourceConfig) -> Iterable[DiscoveredItem]:
        d = source.discovery
        include = [re.compile(p) for p in _patterns(d, "include", "url_include")]
        exclude = [re.compile(p) for p in _patterns(d, "exclude", "url_exclude")]
        allowed = {e.lower() for e in (source.allowed_formats or [])}
        max_urls = int(d.get("max_resources") or d.get("max_urls") or 20000)
        budget = [int(d.get("max_sitemaps") or 100)]
        seen: set[str] = set()
        emitted = 0
        for sm_url in self._sitemap_urls(source):
            for loc, lastmod in self._walk(sm_url, seen, budget):
                if emitted >= max_urls:
                    return
                if include and not any(p.search(loc) for p in include):
                    continue
                if any(p.search(loc) for p in exclude):
                    continue
                path = urlparse(loc).path.lower()
                if allowed and not any(path.endswith(f".{ext}") for ext in allowed):
                    continue
                emitted += 1
                yield DiscoveredItem(
                    url=loc,
                    suggested_filename=filename_from_headers(None, loc),
                    metadata={"lastmod": lastmod, "sitemap": sm_url},
                )

    # -- fetch -----------------------------------------------------------

    def fetch(self, source: SourceConfig, item: DiscoveredItem, workdir) -> FetchResult:
        return _http.fetch(source, item, workdir)

    def inspect(self, result: FetchResult) -> dict:
        return _http.inspect(result)


register(SitemapConnector())
