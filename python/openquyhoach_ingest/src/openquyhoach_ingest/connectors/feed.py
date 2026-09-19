"""RSS/Atom feed connector.

Descriptor::

    source_type: feed
    base_url: https://example.gov.vn/rss/quyhoach.xml
    discovery:
      feed_url: ...            # optional override of base_url
      follow_item_links: false # when true, also fetch item pages for attachments
      url_include/url_exclude/max_items

Items yield enclosure attachments when present (the downloadable
resource); otherwise the item page URL itself is the candidate (an HTML
connector descriptor can still model the detail hop when needed).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlparse

from ..http_client import filename_from_headers
from .base import DiscoveredItem, FetchResult, SourceConfig, register
from .common import _patterns, get_xml
from .http import HttpConnector

_http = HttpConnector()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(el, *names: str) -> str | None:
    for c in el:
        if _local(c.tag) in names and c.text:
            return c.text.strip()
    return None


class FeedConnector:
    source_type = "feed"

    def _entries(self, source: SourceConfig) -> Iterable[dict]:
        url = source.discovery.get("feed_url") or source.base_url
        if not url:
            return
        root = get_xml(url)
        root_tag = _local(root.tag)
        if root_tag == "rss" or root_tag == "channel":
            items = (e for e in root.iter() if _local(e.tag) == "item")
            for it in items:
                enclosures = [
                    c.get("url")
                    for c in it
                    if _local(c.tag) == "enclosure" and c.get("url")
                ]
                yield {
                    "title": _text(it, "title"),
                    "link": _text(it, "link"),
                    "guid": _text(it, "guid"),
                    "published": _text(it, "pubDate", "date"),
                    "enclosures": enclosures,
                }
        elif root_tag == "feed":  # Atom
            for entry in (e for e in root.iter() if _local(e.tag) == "entry"):
                page = None
                enclosures = []
                for c in entry:
                    if _local(c.tag) != "link":
                        continue
                    rel = (c.get("rel") or "alternate").lower()
                    href = c.get("href")
                    if not href:
                        continue
                    if rel == "enclosure":
                        enclosures.append(href)
                    elif rel == "alternate" and page is None:
                        page = href
                yield {
                    "title": _text(entry, "title"),
                    "link": page,
                    "guid": _text(entry, "id"),
                    "published": _text(entry, "updated", "published"),
                    "enclosures": enclosures,
                }

    def discover(self, source: SourceConfig) -> Iterable[DiscoveredItem]:
        d = source.discovery
        include = [re.compile(p) for p in _patterns(d, "include", "url_include")]
        exclude = [re.compile(p) for p in _patterns(d, "exclude", "url_exclude")]
        allowed = {e.lower() for e in (source.allowed_formats or [])}
        max_items = int(d.get("max_resources") or d.get("max_items") or 5000)
        emitted = 0
        for entry in self._entries(source) or ():
            if emitted >= max_items:
                return
            candidates = entry["enclosures"] or ([entry["link"]] if entry["link"] else [])
            for url in candidates:
                if not url:
                    continue
                if include and not any(p.search(url) for p in include):
                    continue
                if any(p.search(url) for p in exclude):
                    continue
                path = urlparse(url).path.lower()
                if allowed and not any(path.endswith(f".{ext}") for ext in allowed):
                    continue
                emitted += 1
                yield DiscoveredItem(
                    url=url,
                    suggested_filename=filename_from_headers(None, url),
                    identity=entry["guid"],
                    metadata={
                        "title": entry["title"],
                        "published": entry["published"],
                        "guid": entry["guid"],
                        "page": entry["link"],
                    },
                )
                break  # one resource per feed item — first enclosure wins

    def fetch(self, source: SourceConfig, item: DiscoveredItem, workdir) -> FetchResult:
        return _http.fetch(source, item, workdir)

    def inspect(self, result: FetchResult) -> dict:
        return _http.inspect(result)


register(FeedConnector())
