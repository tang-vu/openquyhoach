"""Geometry/topology rules. Each rule owns a stable QH-* code."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

import shapely
from openquyhoach_core.enums import QualitySeverity
from shapely.geometry.base import BaseGeometry

from .engine import Finding, ValidationContext, rule

VN_BBOX = (100.0, 5.0, 117.0, 26.0)  # generous lon/lat extent of Vietnam


def _all_features(ctx: ValidationContext):
    for layer in ctx.layers:
        for f in layer.features:
            yield layer, f


def _wkt(geom: BaseGeometry | None) -> str | None:
    if geom is None or geom.is_empty:
        return None
    try:
        return geom.centroid.wkt if not geom.is_valid else geom.wkt[:500]
    except Exception:
        return None


@rule(
    "QH-GEOM-EMPTY",
    "Geometry is empty or null",
    QualitySeverity.ERROR.value,
)
def r_empty(ctx: ValidationContext) -> Iterable[Finding]:
    for layer, f in _all_features(ctx):
        if f.geometry is None or f.geometry.is_empty:
            yield Finding(
                "QH-GEOM-EMPTY",
                QualitySeverity.ERROR.value,
                "empty or missing geometry",
                "feature",
                f.key,
                evidence={"layer": layer.name},
            )


@rule(
    "QH-GEOM-INVALID",
    "Geometry is invalid (self-intersection, unclosed ring, ...)",
    QualitySeverity.ERROR.value,
)
def r_invalid(ctx: ValidationContext) -> Iterable[Finding]:
    for layer, f in _all_features(ctx):
        g = f.geometry
        if g is None or g.is_empty:
            continue
        if not g.is_valid:
            yield Finding(
                "QH-GEOM-INVALID",
                QualitySeverity.ERROR.value,
                f"invalid geometry: {shapely.is_valid_reason(g)}",
                "feature",
                f.key,
                geometry_wkt=_wkt(g),
                evidence={"layer": layer.name},
            )


@rule(
    "QH-GEOM-COLLECTION",
    "GeometryCollection found where atomic geometry expected",
    QualitySeverity.WARNING.value,
)
def r_collection(ctx: ValidationContext) -> Iterable[Finding]:
    for layer, f in _all_features(ctx):
        g = f.geometry
        if g is not None and g.geom_type in ("GeometryCollection",):
            yield Finding(
                "QH-GEOM-COLLECTION",
                QualitySeverity.WARNING.value,
                "GeometryCollection may indicate a conversion artifact",
                "feature",
                f.key,
                geometry_wkt=_wkt(g),
                evidence={"layer": layer.name},
            )


@rule(
    "QH-GEOM-TYPE-MISMATCH",
    "Feature geometry type differs from declared layer type",
    QualitySeverity.ERROR.value,
)
def r_type_mismatch(ctx: ValidationContext) -> Iterable[Finding]:
    _FAMILY = {
        "POINT": {"Point", "MultiPoint"},
        "LINESTRING": {"LineString", "MultiLineString"},
        "POLYGON": {"Polygon", "MultiPolygon"},
    }
    for layer in ctx.layers:
        expected = (layer.expected_geometry_type or layer.geometry_type or "").upper()
        if not expected:
            continue
        family = _FAMILY.get(expected, {expected.title()})
        for f in layer.features:
            if f.geometry is not None and f.geometry.geom_type not in family:
                yield Finding(
                    "QH-GEOM-TYPE-MISMATCH",
                    QualitySeverity.ERROR.value,
                    f"layer {layer.name} expects {expected}, found {f.geometry.geom_type}",
                    "feature",
                    f.key,
                    evidence={"layer": layer.name},
                )


@rule(
    "QH-GEOM-DUPLICATE",
    "Identical geometry appears more than once in a layer",
    QualitySeverity.WARNING.value,
)
def r_duplicate(ctx: ValidationContext) -> Iterable[Finding]:
    for layer in ctx.layers:
        seen: dict[str, str] = {}
        for f in layer.features:
            if f.geometry is None or f.geometry.is_empty:
                continue
            h = hashlib.sha256(shapely.to_wkb(f.geometry)).hexdigest()
            if h in seen:
                yield Finding(
                    "QH-GEOM-DUPLICATE",
                    QualitySeverity.WARNING.value,
                    f"duplicate of feature {seen[h]}",
                    "feature",
                    f.key,
                    geometry_wkt=_wkt(f.geometry),
                    evidence={"layer": layer.name, "duplicate_of": seen[h]},
                )
            else:
                seen[h] = f.key or "?"


@rule(
    "QH-CRS-MISSING",
    "Dataset has no reliably identified CRS — geometry cannot be transformed",
    QualitySeverity.CRITICAL.value,
    applies_to="dataset",
)
def r_crs_missing(ctx: ValidationContext) -> Iterable[Finding]:
    crs = ctx.original_crs or {}
    if not crs.get("identified"):
        yield Finding(
            "QH-CRS-MISSING",
            QualitySeverity.CRITICAL.value,
            "source CRS unidentified; coordinates preserved but NOT transformed",
            "dataset",
            ctx.dataset_id,
            evidence={"crs": crs},
        )


@rule(
    "QH-CRS-BOUNDS",
    "Coordinates fall outside Vietnam's plausible extent — suspicious CRS or data",
    QualitySeverity.WARNING.value,
)
def r_bounds(ctx: ValidationContext) -> Iterable[Finding]:
    crs = ctx.original_crs or {}
    epsg = crs.get("epsg")
    # only meaningful for geographic/lon-lat data in canonical 4326
    if epsg not in (4326, 4756):
        return
    minx, miny, maxx, maxy = VN_BBOX
    for layer, f in _all_features(ctx):
        g = f.geometry
        if g is None or g.is_empty:
            continue
        bx0, by0, bx1, by1 = g.bounds
        if bx1 < minx or bx0 > maxx or by1 < miny or by0 > maxy:
            yield Finding(
                "QH-CRS-BOUNDS",
                QualitySeverity.WARNING.value,
                f"feature bounds {g.bounds} outside Vietnam extent — possible CRS mix-up",
                "feature",
                f.key,
                evidence={"layer": layer.name},
            )


@rule(
    "QH-TOPO-POLY-OVERLAP",
    "Polygons overlap where the layer forbids overlaps",
    QualitySeverity.WARNING.value,
)
def r_poly_overlap(ctx: ValidationContext) -> Iterable[Finding]:
    for layer in ctx.layers:
        if not (ctx.meta.get("topology", {}).get(layer.name, {}).get("no_overlap")):
            continue
        polys = [
            (f.key, f.geometry)
            for f in layer.features
            if f.geometry is not None
            and f.geometry.is_valid
            and f.geometry.geom_type in ("Polygon", "MultiPolygon")
        ]
        for i in range(len(polys)):
            for j in range(i + 1, len(polys)):
                ka, ga = polys[i]
                kb, gb = polys[j]
                if not ga.bounds[2] >= gb.bounds[0] or not ga.bounds[0] <= gb.bounds[2]:
                    continue
                try:
                    inter = ga.intersection(gb)
                except Exception:
                    continue
                if not inter.is_empty and inter.area > 1e-9 * max(ga.area, 1e-12):
                    yield Finding(
                        "QH-TOPO-POLY-OVERLAP",
                        QualitySeverity.WARNING.value,
                        f"polygon {ka} overlaps {kb} (area {inter.area:.3f})",
                        "feature",
                        ka,
                        geometry_wkt=_wkt(inter),
                        evidence={"layer": layer.name, "other": kb},
                    )


@rule(
    "QH-TOPO-POLY-GAP",
    "Coverage polygons leave unexplained gaps",
    QualitySeverity.INFO.value,
)
def r_poly_gap(ctx: ValidationContext) -> Iterable[Finding]:
    for layer in ctx.layers:
        cfg = ctx.meta.get("topology", {}).get(layer.name, {})
        if not cfg.get("no_gaps"):
            continue
        polys = [
            f.geometry
            for f in layer.features
            if f.geometry is not None
            and f.geometry.is_valid
            and f.geometry.geom_type in ("Polygon", "MultiPolygon")
        ]
        if len(polys) < 2:
            continue
        union = shapely.union_all(polys)
        if union.geom_type == "Polygon" and union.interiors:
            yield Finding(
                "QH-TOPO-POLY-GAP",
                QualitySeverity.INFO.value,
                f"coverage union has {len(union.interiors)} interior gap(s)",
                "layer",
                layer.name,
            )


@rule(
    "QH-TOPO-LINE-CROSS",
    "Lines cross where the layer forbids crossings",
    QualitySeverity.WARNING.value,
)
def r_line_cross(ctx: ValidationContext) -> Iterable[Finding]:
    for layer in ctx.layers:
        if not ctx.meta.get("topology", {}).get(layer.name, {}).get("no_line_cross"):
            continue
        lines = [
            (f.key, f.geometry)
            for f in layer.features
            if f.geometry is not None
            and f.geometry.is_valid
            and f.geometry.geom_type in ("LineString", "MultiLineString")
        ]
        for i in range(len(lines)):
            for j in range(i + 1, len(lines)):
                ka, ga = lines[i]
                kb, gb = lines[j]
                try:
                    inter = ga.intersection(gb)
                except Exception:
                    continue
                if not inter.is_empty and inter.geom_type == "Point":
                    yield Finding(
                        "QH-TOPO-LINE-CROSS",
                        QualitySeverity.WARNING.value,
                        f"line {ka} crosses {kb}",
                        "feature",
                        ka,
                        geometry_wkt=_wkt(inter),
                        evidence={"layer": layer.name, "other": kb},
                    )
