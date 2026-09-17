"""Geometry helpers bridging shapely <-> PostGIS without losing provenance."""

from __future__ import annotations

from dataclasses import dataclass

import shapely
from geoalchemy2.shape import from_shape
from shapely.geometry.base import BaseGeometry


@dataclass
class GeomCheck:
    ok: bool
    valid: bool
    empty: bool
    geom_type: str
    reasons: list[str]


def check_geometry(geom: BaseGeometry | None) -> GeomCheck:
    """Cheap structural checks — the full rule set lives in openquyhoach_quality."""
    if geom is None:
        return GeomCheck(False, False, True, "None", ["null_geometry"])
    reasons = []
    if geom.is_empty:
        reasons.append("empty_geometry")
    if not geom.is_valid:
        reasons.append(f"invalid:{shapely.is_valid_reason(geom)}")
    return GeomCheck(
        ok=not reasons,
        valid=geom.is_valid,
        empty=geom.is_empty,
        geom_type=geom.geom_type,
        reasons=reasons,
    )


def to_postgis(geom: BaseGeometry, srid: int = 4326):
    """shapely → geoalchemy2 WKBElement for a typed geometry column."""
    return from_shape(geom, srid=srid)


def ewkb(geom: BaseGeometry, srid: int) -> bytes:
    """EWKB bytes preserving SRID — used to keep source geometry losslessly."""
    return shapely.to_wkb(geom, flavor="extended", hex=False, include_srid=srid != 0)


def from_ewkb(data: bytes) -> tuple[BaseGeometry, int]:
    geom = shapely.from_wkb(data)
    # EWKB stores SRID in the type word; shapely exposes it via get_srid
    return geom, int(shapely.get_srid(geom))


def bounds4326(geom: BaseGeometry) -> list[float]:
    minx, miny, maxx, maxy = geom.bounds
    return [float(minx), float(miny), float(maxx), float(maxy)]


def union_bounds(geoms: list[BaseGeometry]) -> list[float] | None:
    if not geoms:
        return None
    u = shapely.union_all(geoms)
    return bounds4326(u)
