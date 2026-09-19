"""OGC connectors: WFS feature import + WMS metadata harvesting.

WFS: GetCapabilities → per-typename GetFeature (GeoJSON output when the
server supports it, else GML which GDAL reads).
WMS: GetCapabilities metadata only — rasters arrive via tile/rendered
requests handled by the raster path, not bulk download.
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


def _client() -> httpx.Client:
    s = get_settings()
    return httpx.Client(
        headers={"User-Agent": s.fetch_user_agent},
        timeout=s.fetch_timeout_seconds,
        follow_redirects=True,
    )


class WfsConnector:
    source_type = "ogc_wfs"

    def discover(self, source: SourceConfig) -> Iterable[DiscoveredItem]:
        base = (source.base_url or "").split("?")[0]
        caps_url = (
            base
            + "?"
            + urlencode({"service": "WFS", "request": "GetCapabilities", "acceptversions": "2.0.0"})
        )
        check_url_allowed(caps_url)
        with _client() as c:
            resp = c.get(caps_url)
            resp.raise_for_status()
        # FeatureType list via ElementTree (namespace-agnostic)
        import xml.etree.ElementTree as ET

        import re

        from .common import _patterns

        include = [re.compile(p) for p in _patterns(source.discovery, "include", "url_include")]
        exclude = [re.compile(p) for p in _patterns(source.discovery, "exclude", "url_exclude")]
        max_items = int(source.discovery.get("max_resources") or 500)
        emitted = 0
        root = ET.fromstring(resp.content)
        for ft in root.iter():
            if not ft.tag.endswith("FeatureType"):
                continue
            name = title = crs = None
            for child in ft:
                tag = child.tag.rsplit("}", 1)[-1]
                if tag == "Name":
                    name = child.text
                elif tag == "Title":
                    title = child.text
                elif tag in ("DefaultCRS", "DefaultSRS"):
                    crs = child.text
            if not name:
                continue
            if include and not any(p.search(name) for p in include):
                continue
            if any(p.search(name) for p in exclude):
                continue
            emitted += 1
            if emitted > max_items:
                return
            yield DiscoveredItem(
                url=base,
                suggested_filename=f"{name.replace(':', '_')}.geojson",
                metadata={"typename": name, "title": title, "default_crs": crs},
            )

    def fetch(self, source: SourceConfig, item: DiscoveredItem, workdir: Path) -> FetchResult:
        workdir.mkdir(parents=True, exist_ok=True)
        params = {
            "service": "WFS",
            "request": "GetFeature",
            "version": "2.0.0",
            "typenames": item.metadata["typename"],
            "outputFormat": "application/json",
            "srsname": "EPSG:4326",
            "count": source.discovery.get("max_features", 10000),
        }
        url = item.url + "?" + urlencode(params)
        check_url_allowed(url)
        # name the file after the typename: GDAL derives the OGR layer name
        # from the file stem for GeoJSON, so a tempfile would poison
        # layer_map matching and dataset naming
        fname = item.suggested_filename or "features.geojson"
        out = workdir / fname
        with _client() as c:
            resp = c.get(item.url, params=params)
            resp.raise_for_status()
            body = resp.content
        if body[:1] == b"<":
            out = out.with_suffix(".gml")  # server ignored JSON — GDAL parses GML
        out.write_bytes(body)
        from openquyhoach_core.hashing import sha256_file

        sha, size = sha256_file(out)
        return FetchResult(
            local_path=out,
            canonical_url=url,
            retrieved_url=url,
            sha256=sha,
            size=size,
            mime_type="application/gml+xml" if out.suffix == ".gml" else "application/geo+json",
        )

    def inspect(self, result: FetchResult) -> dict:
        return {"detected_format": "geojson" if result.local_path.suffix == ".geojson" else "gml"}


class WmsConnector:
    """WMS: we harvest layer metadata only — WMS renders are derived products,
    never source geometry."""

    source_type = "ogc_wms"

    def discover(self, source: SourceConfig) -> Iterable[DiscoveredItem]:
        base = (source.base_url or "").split("?")[0]
        url = base + "?" + urlencode({"service": "WMS", "request": "GetCapabilities"})
        check_url_allowed(url)
        with _client() as c:
            resp = c.get(url)
            resp.raise_for_status()
        import xml.etree.ElementTree as ET

        root = ET.fromstring(resp.content)
        for layer in root.iter():
            if not layer.tag.endswith("Layer"):
                continue
            name = title = None
            for child in layer:
                tag = child.tag.rsplit("}", 1)[-1]
                if tag == "Name":
                    name = child.text
                elif tag == "Title":
                    title = child.text
            if name:
                yield DiscoveredItem(
                    url=url,
                    suggested_filename=f"wms_{name.replace(':', '_')}.json",
                    metadata={"typename": name, "title": title, "kind": "wms_layer_metadata"},
                )

    def fetch(self, source: SourceConfig, item: DiscoveredItem, workdir: Path) -> FetchResult:
        workdir.mkdir(parents=True, exist_ok=True)
        out = Path(tempfile.mkstemp(dir=workdir, suffix=".json")[1])
        out.write_text(json.dumps({"wms_layer": item.metadata, "capabilities": item.url}))
        from openquyhoach_core.hashing import sha256_file

        sha, size = sha256_file(out)
        return FetchResult(
            local_path=out,
            canonical_url=item.url,
            retrieved_url=item.url,
            sha256=sha,
            size=size,
            mime_type="application/json",
        )

    def inspect(self, result: FetchResult) -> dict:
        return {"detected_format": "json"}


register(WfsConnector())
register(WmsConnector())
