"""OGC API - Features connector (the modern WFS successor).

Descriptor::

    source_type: ogc_api_features
    base_url: https://example.gov.vn/ogc        # API landing page or collections root
    discovery:
      collections_path: /collections   # appended to base_url (default)
      collections: [id1, id2]          # optional allowlist
      page_limit: 1000                 # features per request
      max_features: 50000              # safety cap per collection

Discovery enumerates ``GET {base}/collections``; each collection becomes a
candidate. Fetch pages ``items?limit=…&offset=…`` (or ``next`` links) into
a GeoJSON FeatureCollection artifact.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urljoin

from .base import DiscoveredItem, FetchResult, SourceConfig, register
from .common import get_json


class OgcApiFeaturesConnector:
    source_type = "ogc_api_features"

    def _collections_url(self, source: SourceConfig) -> str:
        base = (source.base_url or "").rstrip("/")
        path = source.discovery.get("collections_path") or "/collections"
        return base + path if not base.endswith(path) else base

    def discover(self, source: SourceConfig) -> Iterable[DiscoveredItem]:
        ua = source.crawl_policy.get("user_agent")
        verify = bool(source.crawl_policy.get("verify_tls", True))
        data = get_json(self._collections_url(source), user_agent=ua, verify_tls=verify)
        allow = set(source.discovery.get("collections") or [])
        cap = int(source.discovery.get("max_resources") or 500)
        emitted = 0
        for col in data.get("collections") or []:
            if emitted >= cap:
                return
            cid = col.get("id")
            if not cid or (allow and cid not in allow):
                continue
            items_url = f"{self._collections_url(source)}/{cid}/items"
            emitted += 1
            yield DiscoveredItem(
                url=items_url,
                suggested_filename=f"{cid}.geojson",
                identity=f"oaf:{cid}",
                metadata={
                    "title": col.get("title") or cid,
                    "collection_id": cid,
                    "description": col.get("description"),
                    "crs": col.get("crs"),
                    "extent": col.get("extent"),
                    "links": [
                        {"rel": link.get("rel"), "href": link.get("href"), "type": link.get("type")}
                        for link in (col.get("links") or [])
                    ],
                },
            )

    def fetch(self, source: SourceConfig, item: DiscoveredItem, workdir: Path) -> FetchResult:
        workdir.mkdir(parents=True, exist_ok=True)
        limit = int(source.discovery.get("page_limit") or 1000)
        max_features = int(source.discovery.get("max_features") or 50000)
        ua = source.crawl_policy.get("user_agent")
        verify = bool(source.crawl_policy.get("verify_tls", True))
        features: list[dict] = []
        url: str | None = item.url
        params: dict | None = {"limit": limit, "f": "json"}
        while url and len(features) < max_features:
            data = get_json(url, params=params, user_agent=ua, verify_tls=verify)
            batch = data.get("features") or []
            features.extend(batch)
            params = None  # next links carry their own query
            url = next(
                (
                    urljoin(item.url, link["href"])
                    for link in (data.get("links") or [])
                    if link.get("rel") == "next"
                ),
                None,
            )
            if not url or len(batch) < limit:
                break
        fc = {
            "type": "FeatureCollection",
            "name": item.metadata.get("collection_id"),
            "features": features[:max_features],
            "openquyhoach": {
                "collection": item.metadata.get("collection_id"),
                "title": item.metadata.get("title"),
                "crs": item.metadata.get("crs"),
                "truncated": len(features) > max_features,
            },
        }
        out = Path(tempfile.mkstemp(dir=workdir, suffix=".geojson")[1])
        out.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
        from openquyhoach_core.hashing import sha256_file

        sha, size = sha256_file(out)
        return FetchResult(
            local_path=out,
            canonical_url=item.url,
            retrieved_url=item.url,
            sha256=sha,
            size=size,
            mime_type="application/geo+json",
            metadata=item.metadata or {},
        )

    def inspect(self, result: FetchResult) -> dict:
        return {"detected_format": "geojson"}


register(OgcApiFeaturesConnector())
