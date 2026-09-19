"""TP.HCM Sở QHKT planning portal — grid enumeration connector.

The official portal (`sqhkt-qlqh.tphcm.gov.vn`, backing
`thongtinquyhoach.hochiminhcity.gov.vn`) exposes no bulk list of approved
zoning plans — only a per-point lookup::

    POST /api/doan/ranhqhpk        form: Lat=<lat>&Lon=<lon>
    -> [{TenDoAn, SoQD, NgayDuyet, CoQuanPD, MaQHPKRanh, Ranh, ...}]

Discovery therefore samples a lat/lon grid over the descriptor's
``discovery.bbox`` and collects the unique ``MaQHPKRanh`` plan codes.
For every unique plan it emits:

1. a boundary item — a synthesised GeoJSON FeatureCollection carrying
   the verbatim API fields as feature properties (fetched via file://);
2. the official plan-map PDF — ``GET {pdf_url_template}`` (http fetch).

Each item's ``metadata.planning_hints`` maps the official API fields to
the pipeline's planning keys, so every artifact resolves to its own
planning record/version with deterministic provenance.
"""

from __future__ import annotations

import json
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path

import httpx
from openquyhoach_core.logging import get_logger
from openquyhoach_core.security import check_url_allowed

from ..http_client import fetch_url
from .base import DiscoveredItem, FetchResult, SourceConfig, register

log = get_logger(__name__)

_FIELD_MAP = {
    "TenDoAn": "plan_title",
    "SoQD": "decision_number",
    "NgayDuyet": "approval_date",
    "CoQuanPD": "approving_authority",
    "DienTich": "area_ha",
    "TrangThai": "status",
    "MaQH": "planning_code",
    "TenQH": "districts",
    "DonViTVTK": "consultant",
    "ChuDauTu": "developer",
}


def _planning_hints(plan: dict) -> dict:
    """Map official API fields → pipeline planning keys (verbatim copies)."""
    hints: dict[str, str] = {}
    if plan.get("TenDoAn"):
        hints["title"] = plan["TenDoAn"]
    if plan.get("SoQD"):
        hints["decision_number"] = plan["SoQD"]
    if plan.get("NgayDuyet"):
        # API uses dd/mm/yyyy → iso
        parts = str(plan["NgayDuyet"]).split("/")
        if len(parts) == 3:
            hints["approval_date"] = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
    if plan.get("CoQuanPD"):
        hints["approving_authority"] = plan["CoQuanPD"]
    if plan.get("MaQHPKRanh"):
        hints["information_code"] = plan["MaQHPKRanh"]
    hints["planning_type"] = "quy_hoach_phan_khu"
    # verbatim copies of the authority's own API fields — deterministic,
    # not pattern-extraction, but still not descriptor-declared official
    hints["_origin"] = "derived_deterministic"
    return hints


def _boundary_geojson(plan: dict) -> dict | None:
    raw = plan.get("Ranh")
    if not raw:
        return None
    try:
        coords = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    props = {dst: plan.get(src) for src, dst in _FIELD_MAP.items() if plan.get(src)}
    props["MaQHPKRanh"] = plan.get("MaQHPKRanh")
    props["STT"] = plan.get("STT")
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "MultiPolygon", "coordinates": coords},
                "properties": props,
            }
        ],
    }


class SqHktGridConnector:
    """Grid-sample the QHKT point-lookup API to enumerate approved plans."""

    source_type = "sqhkt_grid"

    def discover(self, source: SourceConfig) -> Iterable[DiscoveredItem]:
        disc = source.discovery or {}
        bbox = disc.get("bbox") or [106.55, 10.35, 107.05, 11.25]
        step = float(disc.get("grid_step") or 0.02)
        delay = float((source.crawl_policy or {}).get("delay_seconds") or 0.4)
        point_path = disc.get("point_endpoint") or "/api/doan/ranhqhpk"
        pdf_template = disc.get("pdf_url_template") or (
            "/api/bandogiay/download-pdf/QHPK/{ma}"
        )
        base = (source.base_url or "").rstrip("/")
        point_url = base + point_path
        check_url_allowed(point_url)  # SSRF guard on the POST endpoint

        ua = (source.crawl_policy or {}).get("user_agent") or "OpenQuyHoach/0.1"
        verify = bool((source.crawl_policy or {}).get("verify_tls", True))
        plans: dict[str, dict] = {}
        probed = 0
        lat = bbox[1]
        with httpx.Client(
            headers={"User-Agent": ua},
            timeout=30.0,
            follow_redirects=False,
            verify=verify,
        ) as client:
            while lat <= bbox[3] + 1e-9:
                lon = bbox[0]
                while lon <= bbox[2] + 1e-9:
                    try:
                        resp = client.post(
                            point_url,
                            data={"Lat": f"{lat:.5f}", "Lon": f"{lon:.5f}"},
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            rows = data if isinstance(data, list) else [data]
                            for plan in rows:
                                ma = plan.get("MaQHPKRanh")
                                if ma:
                                    plans.setdefault(ma, plan)
                    except (httpx.HTTPError, json.JSONDecodeError):
                        pass  # offshore/unavailable point — keep sweeping
                    probed += 1
                    if delay:
                        time.sleep(delay)
                    lon += step
                lat += step
        log.info(
            "sqhkt_grid.discovered",
            plans=len(plans),
            probed=probed,
            step=step,
            bbox=bbox,
        )

        work = Path(tempfile.mkdtemp(prefix="oqh-sqhkt-"))
        for ma, plan in plans.items():
            hints = _planning_hints(plan)
            meta = {
                "title": plan.get("TenDoAn"),
                "ma": ma,
                "planning_hints": hints,
                "api_fields": plan,
            }
            gj = _boundary_geojson(plan)
            if gj is not None:
                safe_ma = "".join(c if c.isalnum() or c in "-_" else "_" for c in ma)
                gpath = work / f"qhpk_ranh_{safe_ma}.geojson"
                gpath.write_text(
                    json.dumps(gj, ensure_ascii=False), encoding="utf-8"
                )
                yield DiscoveredItem(
                    url=f"file://{gpath}",
                    suggested_filename=gpath.name,
                    metadata=meta,
                    identity=f"sqhkt-ranh-{ma}",
                )
            yield DiscoveredItem(
                url=base + pdf_template.format(ma=ma),
                suggested_filename=f"qhpk_bandoso_{ma}.pdf",
                metadata=meta,
                identity=f"sqhkt-bandoso-{ma}",
            )

    def fetch(
        self, source: SourceConfig, item: DiscoveredItem, workdir: Path
    ) -> FetchResult:
        if item.url.startswith("file://"):
            # synthesised boundary file — copy into the run workdir
            import shutil

            from openquyhoach_core.hashing import sha256_file

            src = Path(item.url.replace("file://", ""))
            workdir.mkdir(parents=True, exist_ok=True)
            if item.suggested_filename:
                tmp = workdir / Path(item.suggested_filename).name
            else:
                tmp = Path(
                    tempfile.mkstemp(dir=workdir, prefix="sqhkt-", suffix=".geojson")[1]
                )
            shutil.copyfile(src, tmp)
            sha, size = sha256_file(tmp)
            return FetchResult(
                local_path=tmp,
                canonical_url=item.url,
                retrieved_url=item.url,
                sha256=sha,
                size=size,
                mime_type="application/geo+json",
            )
        res = fetch_url(
            item.url,
            workdir,
            etag=item.etag,
            last_modified=item.last_modified,
            crawl_delay=float((source.crawl_policy or {}).get("delay_seconds", 0)),
            max_bytes=(source.rate_limit or {}).get("max_bytes"),
            user_agent=(source.crawl_policy or {}).get("user_agent"),
            verify_tls=bool((source.crawl_policy or {}).get("verify_tls", True)),
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


register(SqHktGridConnector())
