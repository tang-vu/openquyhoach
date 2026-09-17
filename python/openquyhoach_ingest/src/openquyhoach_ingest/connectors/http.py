"""Generic HTTP connector — direct file URLs and simple metadata endpoints."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from openquyhoach_core.security import sniff_format

from ..http_client import fetch_url
from .base import DiscoveredItem, FetchResult, SourceConfig, register


class HttpConnector:
    source_type = "http"

    def discover(self, source: SourceConfig) -> Iterable[DiscoveredItem]:
        urls = source.discovery.get("urls") or ([source.base_url] if source.base_url else [])
        for u in urls:
            yield DiscoveredItem(url=u)

    def fetch(self, source: SourceConfig, item: DiscoveredItem, workdir: Path) -> FetchResult:
        res = fetch_url(
            item.url,
            workdir,
            etag=item.etag,
            last_modified=item.last_modified,
            crawl_delay=float(source.crawl_policy.get("delay_seconds", 0)),
        )
        if res.get("not_modified"):
            return FetchResult(
                local_path=Path(""),
                canonical_url=item.url,
                retrieved_url=item.url,
                sha256="",
                size=0,
                not_modified=True,
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
        )

    def inspect(self, result: FetchResult) -> dict:
        head = result.local_path.read_bytes()[:512]
        return {"detected_format": sniff_format(head, result.local_path.name)}


register(HttpConnector())
