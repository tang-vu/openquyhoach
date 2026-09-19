"""eKGIS planning-portal grid enumeration connector.

Several provincial planning portals run the eKGIS stack — an Angular app
backed by ``QuyHoachServices/rest/QuyHoach/gsv_data/<org>/<db>/`` REST
endpoints on the official ``*.gov.vn`` domain (verified: Hải Phòng
``quyhoach.haiphong.gov.vn`` and Hà Nội ``qhkhsdd.hanoi.gov.vn``).

The portals expose no bulk plan list. Discovery grid-samples the
point-lookup endpoint::

    GET {point_endpoint}?lng={LNG}&lat={LAT}
    -> JSON-encoded JSON string with arrays:
       doanquyhoach (plan boundary + metadata, geom as WKT),
       oquyhoach / ochucnangsudungdat / lodat / khuquyhoach (zoning cells)

Unique plans are deduplicated by ``maHoSo``/``maLienKet``/``maThongTinQH``
(first non-empty of ``discovery.id_fields``). For each plan the connector
fetches the authoritative detail endpoint::

    GET {detail_endpoint}?maDoAn={ma}   -> [plan record incl. WKT geom]

and emits a synthesised GeoJSON FeatureCollection (verbatim fields in
properties + raw API record under ``openquyhoach.raw``) via ``file://``
staging — the same provenance-preserving pattern as ``sqhkt_grid``.

Zoning-cell arrays are intentionally not harvested by grid sweep: cells
are too small for reliable enumeration at plan-boundary grid spacing.
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
    "tenDoAn": "plan_title",
    "soQDQH": "decision_number",
    "ngayQDQH": "approval_date",
    "coQuanPheduyet": "approving_authority",
    "dienTichQH": "area_ha",
    "trangThaiDoAn": "status",
    "phanLoai": "plan_category",
    "loaiQuyHoach": "planning_type_raw",
    "capDoQuyHoach": "planning_level_raw",
    "donViTuVan": "consultant",
    "chuDauTu": "developer",
    "diaDiemQH": "location",
    "tenTinh": "province_name",
    "tenXa": "commune_name",
    "ghiChu": "notes",
}


def _clean(v):
    """eKGIS returns the literal string 'None' for nulls."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("none", "null"):
        return None
    return s


def _planning_hints(plan: dict) -> dict:
    hints: dict[str, str] = {}
    for src, dst in (
        ("tenDoAn", "title"),
        ("soQDQH", "decision_number"),
        ("coQuanPheduyet", "approving_authority"),
        ("maHoSo", "information_code"),
        ("dienTichQH", "area_ha"),
        ("trangThaiDoAn", "status"),
    ):
        v = _clean(plan.get(src))
        if v:
            hints[dst] = v
    ngay = _clean(plan.get("ngayQDQH"))
    if ngay:
        parts = ngay.replace("-", "/").split("/")
        if len(parts) == 3 and len(parts[0]) == 4:  # yyyy/mm/dd
            hints["approval_date"] = "-".join(parts)
        elif len(parts) == 3:  # dd/mm/yyyy
            hints["approval_date"] = (
                f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
            )
        else:
            hints["approval_date"] = ngay[:10]
    loai = _clean(plan.get("loaiQuyHoach")) or _clean(plan.get("phanLoai"))
    if loai:
        hints["planning_type"] = loai
    hints["_origin"] = "derived_deterministic"
    return hints


def _wkt_to_geometry(wkt_str: str):
    from shapely import wkt as _wkt
    from shapely.geometry import mapping

    geom = _wkt.loads(wkt_str)
    return mapping(geom)


def _plan_geojson(plan: dict) -> dict | None:
    wkt_str = plan.get("geom")
    if not wkt_str or not str(wkt_str).strip():
        return None
    try:
        geometry = _wkt_to_geometry(str(wkt_str))
    except Exception:
        return None
    props = {dst: _clean(plan.get(src)) for src, dst in _FIELD_MAP.items()}
    props = {k: v for k, v in props.items() if v is not None}
    for key in ("maHoSo", "maLienKet", "maThongTinQH", "maDoiTuong", "maHoSoQH"):
        v = _clean(plan.get(key))
        if v:
            props[key] = v
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": geometry, "properties": props}
        ],
        "openquyhoach": {"raw": plan},
    }


def _unwrap(resp: httpx.Response):
    """eKGIS wraps payloads in a JSON string; parse until structured."""
    data = resp.json()
    for _ in range(3):
        if isinstance(data, str):
            data = json.loads(data)
        else:
            break
    return data


class EkgisGridConnector:
    """Grid-sample an eKGIS point-lookup endpoint to enumerate plans."""

    source_type = "ekgis_grid"

    def _client(self, source: SourceConfig) -> httpx.Client:
        ua = (source.crawl_policy or {}).get("user_agent") or "OpenQuyHoach/0.1"
        verify = bool((source.crawl_policy or {}).get("verify_tls", True))
        return httpx.Client(
            headers={"User-Agent": ua},
            timeout=30.0,
            follow_redirects=False,
            verify=verify,
        )

    def _plan_id(self, plan: dict, id_fields: list[str]) -> str | None:
        for f in id_fields:
            v = _clean(plan.get(f))
            if v:
                return v
        return None

    def _sweep(
        self,
        source: SourceConfig,
        client: httpx.Client,
        point_url: str,
        bbox: list,
        step: float,
        delay: float,
        array_name: str,
        id_fields: list[str],
    ) -> dict[str, dict]:
        """Grid-sample the point-lookup endpoint; dedupe plans by id fields."""
        plans: dict[str, dict] = {}
        probed = errors = 0
        first_error: str | None = None
        lat = bbox[1]
        while lat <= bbox[3] + 1e-9:
            lon = bbox[0]
            while lon <= bbox[2] + 1e-9:
                try:
                    resp = client.get(
                        point_url,
                        params={"lng": f"{lon:.5f}", "lat": f"{lat:.5f}"},
                    )
                    if resp.status_code == 200:
                        data = _unwrap(resp)
                        rows = data.get(array_name) or [] if isinstance(data, dict) else []
                        for plan in rows:
                            pid = self._plan_id(plan, id_fields)
                            if pid:
                                plans.setdefault(pid, plan)
                except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
                    errors += 1
                    if first_error is None:
                        first_error = str(exc)
                probed += 1
                if delay:
                    time.sleep(delay)
                lon += step
            lat += step
        log.info(
            "ekgis_grid.discovered",
            plans=len(plans), probed=probed, errors=errors, step=step, bbox=bbox,
        )
        # a sweep that found nothing *because requests failed* is a failure,
        # not an empty result — surface it instead of marking the source clean
        if not plans and probed and errors == probed:
            raise RuntimeError(
                f"ekgis_grid: all {probed} point lookups failed: {first_error}"
            )
        return plans

    def _fetch_detail(
        self,
        source: SourceConfig,
        base: str,
        detail_url: str | None,
        pid: str,
        plan: dict,
        delay: float,
    ) -> dict:
        """Fetch the authoritative detail record; merge over the sweep hit."""
        if not detail_url:
            return plan
        detail = None
        try:
            durl = base + detail_url.format(ma=pid)
            check_url_allowed(durl)
            with self._client(source) as client:
                r = client.get(durl)
            if r.status_code == 200:
                dd = _unwrap(r)
                if isinstance(dd, list) and dd:
                    # detail record is authoritative — keep its geom
                    detail = {**plan, **dd[0]}
                elif isinstance(dd, dict):
                    detail = {**plan, **dd}
        except (httpx.HTTPError, json.JSONDecodeError, ValueError):
            detail = None
        if delay:
            time.sleep(delay)
        return detail or plan

    def discover(self, source: SourceConfig) -> Iterable[DiscoveredItem]:
        disc = source.discovery or {}
        bbox = disc.get("bbox")
        if not bbox or len(bbox) != 4:
            raise ValueError("ekgis_grid requires discovery.bbox [minLon,minLat,maxLon,maxLat]")
        step = float(disc.get("grid_step") or 0.02)
        delay = float((source.crawl_policy or {}).get("delay_seconds") or 0.4)
        base = (source.base_url or "").rstrip("/")
        point_url = base + (disc.get("point_endpoint")
                            or "/QuyHoachServices/rest/QuyHoach/gsv_data")
        detail_url = disc.get("detail_endpoint")  # contains {ma}
        id_fields = disc.get("id_fields") or ["maHoSo", "maLienKet", "maThongTinQH"]
        array_name = disc.get("response_array") or "doanquyhoach"
        check_url_allowed(point_url)

        with self._client(source) as client:
            plans = self._sweep(
                source, client, point_url, bbox, step, delay, array_name, id_fields
            )

        work = Path(tempfile.mkdtemp(prefix="oqh-ekgis-"))
        for pid, plan in plans.items():
            merged = self._fetch_detail(source, base, detail_url, pid, plan, delay)
            gj = _plan_geojson(merged)
            hints = _planning_hints(merged)
            meta = {
                "title": _clean(merged.get("tenDoAn")),
                "ma": pid,
                "planning_hints": hints,
                "api_fields": merged,
            }
            if gj is None:
                continue
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in pid)
            gpath = work / f"ekgis_{safe}.geojson"
            gpath.write_text(json.dumps(gj, ensure_ascii=False), encoding="utf-8")
            yield DiscoveredItem(
                url=f"file://{gpath}",
                suggested_filename=gpath.name,
                metadata=meta,
                identity=f"ekgis-{pid}",
            )

    def fetch(
        self, source: SourceConfig, item: DiscoveredItem, workdir: Path
    ) -> FetchResult:
        if item.url.startswith("file://"):
            import shutil

            from openquyhoach_core.hashing import sha256_file

            src = Path(item.url.replace("file://", ""))
            workdir.mkdir(parents=True, exist_ok=True)
            tmp = Path(
                tempfile.mkstemp(dir=workdir, prefix="ekgis-", suffix=".geojson")[1]
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


register(EkgisGridConnector())
