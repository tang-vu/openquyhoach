"""Normalized Vietnamese search + coordinate/URL query parsing.

Search is PostgreSQL-only by design (normalized columns + pg_trgm). The
geocoder provider interface exists so a deployment can plug a real geocoder
without touching callers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from openquyhoach_core.db import session_scope
from openquyhoach_core.models import AdministrativeUnit, Document, PlanningRecord
from openquyhoach_core.text import vn_normalize
from sqlalchemy import func, or_

_COORD = re.compile(r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")
_URL_COORD = re.compile(r"[?#&](?:lat|y)=(-?\d{1,3}(?:\.\d+)?)[&\w=.,%-]*")
_URL_LON = re.compile(r"[?#&](?:lon|lng|x)=(-?\d{1,3}(?:\.\d+)?)")
_URL_MAPSTATE = re.compile(r"#map=([\d.]+)/(-?\d{1,3}(?:\.\d+)?)/(-?\d{1,3}(?:\.\d+)?)")


@dataclass
class SearchResult:
    kind: str  # planning_record|admin_unit|document|coordinate
    id: str | None
    title: str
    subtitle: str | None = None
    lon: float | None = None
    lat: float | None = None
    meta: dict | None = None


class Geocoder(Protocol):
    def geocode(self, query: str) -> SearchResult | None: ...


class NoopGeocoder:
    """Default: no external geocoder configured."""

    def geocode(self, query: str) -> SearchResult | None:
        return None


def parse_coordinates(q: str) -> tuple[float, float] | None:
    """(lon, lat) from 'lon, lat' text or a shared map URL."""
    m = _COORD.match(q)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        # VN heuristic: latitude is ~8-23, longitude ~102-110; allow both orders
        if abs(a) <= 90 and abs(b) > 90:
            return b, a
        return a, b
    m = _URL_MAPSTATE.search(q)
    if m:
        return float(m.group(3)), float(m.group(2))  # maplibre: z/lon/lat
    lat_m, lon_m = _URL_COORD.search(q), _URL_LON.search(q)
    if lat_m and lon_m:
        return float(lon_m.group(1)), float(lat_m.group(1))
    return None


def search(
    query: str,
    *,
    limit: int = 10,
    geocoder: Geocoder | None = None,
) -> list[SearchResult]:
    q = query.strip()
    if not q:
        return []
    coord = parse_coordinates(q)
    if coord:
        lon, lat = coord
        return [
            SearchResult(
                kind="coordinate", id=None, title=f"{lat:.5f}, {lon:.5f}", lon=lon, lat=lat
            )
        ]

    norm = vn_normalize(q)
    like = f"%{norm}%"
    results: list[SearchResult] = []
    with session_scope() as s:
        for r in (
            s.query(PlanningRecord)
            .filter(PlanningRecord.normalized_title.like(like))
            .order_by(func.length(PlanningRecord.normalized_title))
            .limit(limit)
            .all()
        ):
            results.append(
                SearchResult(
                    kind="planning_record",
                    id=str(r.id),
                    title=r.title,
                    subtitle=r.jurisdiction,
                    meta={"planning_type": r.planning_type, "code": r.official_information_code},
                )
            )
        for a in (
            s.query(AdministrativeUnit)
            .filter(AdministrativeUnit.normalized_name.like(like))
            .order_by(func.length(AdministrativeUnit.normalized_name))
            .limit(limit)
            .all()
        ):
            results.append(
                SearchResult(
                    kind="admin_unit",
                    id=str(a.id),
                    title=a.name,
                    subtitle=a.level,
                    lon=None,
                    lat=None,
                    meta={"code": a.official_code},
                )
            )
        for d in (
            s.query(Document)
            .filter(
                or_(Document.normalized_title.like(like), Document.document_number.ilike(f"%{q}%"))
            )
            .limit(limit)
            .all()
        ):
            results.append(
                SearchResult(
                    kind="document",
                    id=str(d.id),
                    title=d.title or d.document_number or "?",
                    subtitle=d.document_type,
                    meta={"document_number": d.document_number},
                )
            )
    if not results and geocoder:
        hit = geocoder.geocode(q)
        if hit:
            results.append(hit)
    return results[:limit]
