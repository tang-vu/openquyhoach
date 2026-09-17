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
        """Enumerate layers of a MapServer/FeatureServer."""
        base = (source.base_url or "").rstrip("/")
        if not base:
            return
        svc = self._json(base)
        for layer in svc.get("layers", []):
            lid = layer["id"]
            meta = self._json(f"{base}/{lid}")
            yield DiscoveredItem(
                url=f"{base}/{lid}/query",
                suggested_filename=f"{meta.get('name', f'layer_{lid}')}.geojson",
                metadata={
                    "layer_id": lid,
                    "layer_name": meta.get("name"),
                    "geometry_type": meta.get("geometryType"),
                    "spatial_reference": meta.get("extent", {}).get("spatialReference")
                    or meta.get("spatialReference"),
                    "fields": meta.get("fields"),
                    "service": base,
                },
            )

    def fetch(self, source: SourceConfig, item: DiscoveredItem, workdir: Path) -> FetchResult:
        """Page through features as GeoJSON, 2000/page (ArcGIS default cap)."""
        workdir.mkdir(parents=True, exist_ok=True)
        out_path = Path(tempfile.mkstemp(dir=workdir, suffix=".geojson")[1])
        offset = 0
        page = 2000
        features = []
        with self._client() as c:
            while True:
                params: dict[str, str | int] = {
                    "where": "1=1",
                    "outFields": "*",
                    "returnGeometry": "true",
                    "f": "geojson",
                    "resultOffset": offset,
                    "resultRecordCount": page,
                    "outSR": 4326,
                }
                url = item.url + "?" + urlencode(params)
                check_url_allowed(url)
                resp = c.get(item.url, params=params)
                resp.raise_for_status()
                data = resp.json()
                if data.get("error"):
                    raise RuntimeError(f"ArcGIS query error: {data['error'].get('message')}")
                batch = data.get("features", [])
                features.extend(batch)
                if len(batch) < page:
                    break
                offset += page
        fc = {
            "type": "FeatureCollection",
            "name": item.metadata.get("layer_name"),
            "features": features,
            "openquyhoach": {"source_spatial_reference": item.metadata.get("spatial_reference")},
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
