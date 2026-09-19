"""CKAN catalog connector (data.gov-style open data portals).

Descriptor::

    source_type: ckan
    base_url: https://data.example.gov.vn        # CKAN site root
    discovery:
      query: "quy hoạch"          # package_search q (optional)
      fq: "organization:thon"     # package_search fq (optional)
      package_ids: [slug-or-id]   # explicit packages (skips search)
      rows: 100                   # page size, <=1000
      formats: [GEOJSON, SHP, ZIP, PDF]   # resource format allowlist

Each CKAN *resource* becomes a candidate keyed by its stable resource id —
URL churn produces ``url_changed`` events, not phantom new resources.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..http_client import filename_from_headers
from .base import DiscoveredItem, FetchResult, SourceConfig, register
from .common import get_json
from .http import HttpConnector

_http = HttpConnector()


class CkanConnector:
    source_type = "ckan"

    def _api(self, source: SourceConfig, action: str, params: dict) -> dict:
        base = (source.base_url or "").rstrip("/")
        ua = source.crawl_policy.get("user_agent")
        data = get_json(f"{base}/api/3/action/{action}", params=params, user_agent=ua)
        if not data.get("success"):
            raise RuntimeError(f"CKAN {action} failed: {data.get('error')}")
        return data["result"]

    def _packages(self, source: SourceConfig) -> Iterable[dict]:
        d = source.discovery
        ids = d.get("package_ids") or []
        if ids:
            for pid in ids:
                try:
                    yield self._api(source, "package_show", {"id": pid})
                except Exception:
                    continue
            return
        rows = min(int(d.get("row_limit") or d.get("rows") or 100), 1000)
        fq_parts = [d.get("fq")] if d.get("fq") else []
        if d.get("organization"):
            fq_parts.append(f"organization:{d['organization']}")
        start = 0
        while True:
            result = self._api(
                source,
                "package_search",
                {
                    "q": d.get("package_query") or d.get("query") or "*:*",
                    "fq": " ".join(fq_parts),
                    "rows": rows,
                    "start": start,
                },
            )
            batch = result.get("results") or []
            yield from batch
            start += len(batch)
            if not batch or start >= result.get("count", 0):
                break

    def discover(self, source: SourceConfig) -> Iterable[DiscoveredItem]:
        allowed = {f.lower() for f in (source.discovery.get("formats") or [])}
        seen: set[str] = set()
        for pkg in self._packages(source):
            org = (pkg.get("organization") or {}).get("title")
            for res in pkg.get("resources") or []:
                rid = res.get("id")
                url = res.get("url")
                if not url or (rid and rid in seen):
                    continue
                fmt = (res.get("format") or "").strip().lower()
                if allowed and fmt not in allowed:
                    continue
                if rid:
                    seen.add(rid)
                yield DiscoveredItem(
                    url=url,
                    suggested_filename=filename_from_headers(None, url),
                    identity=f"ckan:{rid}" if rid else None,
                    metadata={
                        "title": res.get("name") or res.get("description") or url.rsplit("/", 1)[-1],
                        "package_id": pkg.get("id"),
                        "package_name": pkg.get("name"),
                        "package_title": pkg.get("title"),
                        "organization": org,
                        "resource_id": rid,
                        "format": fmt or None,
                        "mimetype": res.get("mimetype"),
                        "resource_last_modified": res.get("last_modified"),
                        "revision_id": res.get("revision_id"),
                    },
                )

    def fetch(self, source: SourceConfig, item: DiscoveredItem, workdir: Path) -> FetchResult:
        return _http.fetch(source, item, workdir)

    def inspect(self, result: FetchResult) -> dict:
        return _http.inspect(result)


register(CkanConnector())
