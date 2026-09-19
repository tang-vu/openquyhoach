"""ArcGIS REST connector (MapServer / FeatureServer).

Discovers layers from the service JSON, then pages features via
``where=1=1&outFields=*&f=geojson`` with resultOffset pagination — all
metadata (spatialReference, fields, layer names) is preserved.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlencode

import httpx
from openquyhoach_core.security import check_url_allowed
from openquyhoach_core.settings import get_settings

from .base import DiscoveredItem, FetchResult, SourceConfig, register
from .common import _patterns


def _query(c: httpx.Client, url: str, params: dict) -> dict:
    check_url_allowed(url + "?" + urlencode(params))
    resp = c.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise RuntimeError(f"ArcGIS query error: {data['error'].get('message')}")
    return data


class ArcgisRestConnector:
    source_type = "arcgis_rest"

    def _client(self) -> httpx.Client:
        s = get_settings()
        return httpx.Client(
            headers={"User-Agent": s.fetch_user_agent},
            timeout=s.fetch_timeout_seconds,
            follow_redirects=True,
        )

    def _json(self, url: str, params: dict | None = None) -> dict:
        check_url_allowed(url)
        q = {"f": "json", **(params or {})}
        with self._client() as c:
            resp = c.get(url, params=q)
            resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"ArcGIS error: {data['error'].get('message')}")
        return data

    def discover(self, source: SourceConfig) -> Iterable[DiscoveredItem]:
        """Enumerate layers of one or more MapServer/FeatureServer services.

        ``discovery.services`` may hold a list of service URLs (multiple
        MapServers under one descriptor); ``source.base_url`` remains the
        single-service shorthand. ``include``/``exclude`` regexes filter
        layer names — same convention as the WFS connector.
        """
        import re

        bases = []
        if source.base_url:
            bases.append(source.base_url.rstrip("/"))
        for u in source.discovery.get("services") or []:
            bases.append(u.rstrip("/"))
        include = [re.compile(p) for p in _patterns(source.discovery, "include", "url_include")]
        exclude = [re.compile(p) for p in _patterns(source.discovery, "exclude", "url_exclude")]
        max_items = int(source.discovery.get("max_resources") or 5000)
        emitted = 0
        for base in bases:
            svc = self._json(base)
            for layer in svc.get("layers", []):
                if emitted >= max_items:
                    return
                lid = layer["id"]
                meta = self._json(f"{base}/{lid}")
                lname = meta.get("name") or f"layer_{lid}"
                if include and not any(p.search(lname) for p in include):
                    continue
                if any(p.search(lname) for p in exclude):
                    continue
                fields = meta.get("fields") or []
                oid_field = next(
                    (f["name"] for f in fields if f.get("type") == "esriFieldTypeOID"),
                    None,
                )
                caps = meta.get("advancedQueryCapabilities") or {}
                supports_pagination = bool(
                    caps.get("supportsPagination", meta.get("supportsPagination", True))
                )
                emitted += 1
                yield DiscoveredItem(
                    url=f"{base}/{lid}/query",
                    suggested_filename=f"{lname}.geojson",
                    metadata={
                        "layer_id": lid,
                        "layer_name": lname,
                        "geometry_type": meta.get("geometryType"),
                        "spatial_reference": meta.get("extent", {}).get("spatialReference")
                        or meta.get("spatialReference"),
                        "fields": fields,
                        "service": base,
                        "max_record_count": meta.get("maxRecordCount"),
                        "oid_field": oid_field,
                        "supports_pagination": supports_pagination,
                    },
                )

    def _offset_pages(self, c: httpx.Client, url: str, page: int) -> list:
        """Standard resultOffset paging; falls back to OID-range paging on
        pre-10.3 servers that reject the pagination params."""
        features: list = []
        offset = 0
        try:
            while True:
                data = _query(c, url, {
                    "where": "1=1",
                    "outFields": "*",
                    "returnGeometry": "true",
                    "f": "geojson",
                    "resultOffset": offset,
                    "resultRecordCount": page,
                    "outSR": 4326,
                })
                batch = data.get("features", [])
                features.extend(batch)
                if len(batch) < page:
                    break
                offset += page
        except RuntimeError as exc:
            if "Pagination is not supported" in str(exc):
                return self._oid_pages(c, url, page, None)
            raise
        return features

    def _oid_pages(self, c: httpx.Client, url: str, page: int, oid_field: str | None) -> list:
        """Page via `where OID > last` — works on servers without any
        pagination support. ``resultRecordCount``/``orderByFields`` are
        dropped on servers that reject them; the server's implicit cap is
        learned from the first uncounted batch."""
        if not oid_field:
            lmeta = self._json(url.rsplit("/query", 1)[0])
            oid_field = next(
                (f["name"] for f in (lmeta.get("fields") or [])
                 if f.get("type") == "esriFieldTypeOID"),
                None,
            )
            if not oid_field:
                raise RuntimeError("layer has no OID field for paging fallback")
        features: list = []
        last = -1
        with_order = with_count = True
        expected: int | None = page
        while True:
            params: dict = {
                "where": f"{oid_field} > {last}",
                "outFields": "*",
                "returnGeometry": "true",
                "f": "geojson",
                "outSR": 4326,
            }
            if with_order:
                params["orderByFields"] = f"{oid_field} ASC"
            if with_count:
                params["resultRecordCount"] = page
            try:
                data = _query(c, url, params)
            except RuntimeError as exc:
                msg = str(exc).lower()
                if "pagination" in msg and with_count:
                    with_count, expected = False, None  # pre-10.3 — learn cap
                    continue
                if "order" in msg and with_order:
                    with_order = False
                    continue
                raise
            batch = data.get("features", [])
            features.extend(batch)
            if expected is None:
                expected = max(1, len(batch))
            if not batch or len(batch) < expected:
                break
            last = max(f["properties"][oid_field] for f in batch)
        return features

    def fetch(self, source: SourceConfig, item: DiscoveredItem, workdir: Path) -> FetchResult:
        """Page through features as GeoJSON.

        Page size honours the service's ``maxRecordCount``; layers whose
        server rejects ``resultOffset`` ("Pagination is not supported")
        fall back to OBJECTID-range paging — silent truncation at the
        server cap is not acceptable. The server-side feature count is
        recorded in the collection's ``openquyhoach`` block for audit.
        """
        workdir.mkdir(parents=True, exist_ok=True)
        out_path = Path(tempfile.mkstemp(dir=workdir, suffix=".geojson")[1])
        meta = item.metadata or {}
        page = min(2000, int(meta.get("max_record_count") or 2000))
        features: list = []
        with self._client() as c:
            try:
                server_count = _query(c, item.url, {
                    "where": "1=1", "returnCountOnly": "true", "f": "json",
                }).get("count")
            except Exception:
                server_count = None
            if meta.get("supports_pagination", True):
                features.extend(self._offset_pages(c, item.url, page))
            elif meta.get("oid_field"):
                features.extend(self._oid_pages(c, item.url, page, meta["oid_field"]))
            else:
                data = _query(c, item.url, {
                    "where": "1=1", "outFields": "*",
                    "returnGeometry": "true", "f": "geojson", "outSR": 4326,
                })
                features.extend(data.get("features", []))
        fc = {
            "type": "FeatureCollection",
            "name": meta.get("layer_name"),
            "features": features,
            "openquyhoach": {
                "source_spatial_reference": meta.get("spatial_reference"),
                "server_feature_count": server_count,
            },
        }
        out_path.write_text(json.dumps(fc, ensure_ascii=False))
        from openquyhoach_core.hashing import sha256_file

        sha, size = sha256_file(out_path)
        return FetchResult(
            local_path=out_path,
            canonical_url=item.url,
            retrieved_url=item.url,
            sha256=sha,
            size=size,
            mime_type="application/geo+json",
        )

    def inspect(self, result: FetchResult) -> dict:
        return {"detected_format": "geojson"}


register(ArcgisRestConnector())
