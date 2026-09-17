"""Version comparison — ChangeSet computation.

Pairs features across two compatible layers by `stable_external_id` (falling
back to source_object_code), then classifies each pair:

    added | removed | geometry_changed | classification_changed | properties_changed

Geometry deltas are computed in PostGIS on request; the service itself only
needs shapely for offline/testable comparison.

It never infers legal meaning from geometric difference — the ChangeSet is a
*geometric/attribute* statement, not a legal one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from geoalchemy2.shape import to_shape
from openquyhoach_core.db import session_scope
from openquyhoach_core.models import ChangeSet, ChangeSetEntry, Feature
from shapely.geometry.base import BaseGeometry

GEOM_TOLERANCE_DEG = 1e-9  # ~0.1mm at equator — exact-match with wiggle room


@dataclass
class FeatureView:
    id: str
    key: str | None
    classification: str | None
    geometry: BaseGeometry | None
    properties: dict


@dataclass
class DiffResult:
    added: list[FeatureView] = field(default_factory=list)
    removed: list[FeatureView] = field(default_factory=list)
    geometry_changed: list[tuple[FeatureView, FeatureView, float]] = field(default_factory=list)
    classification_changed: list[tuple[FeatureView, FeatureView]] = field(default_factory=list)
    properties_changed: list[tuple[FeatureView, FeatureView, dict]] = field(default_factory=list)
    unchanged: int = 0

    def summary(self) -> dict:
        return {
            "added": len(self.added),
            "removed": len(self.removed),
            "geometry_changed": len(self.geometry_changed),
            "classification_changed": len(self.classification_changed),
            "properties_changed": len(self.properties_changed),
            "unchanged": self.unchanged,
        }


def _key(f: FeatureView) -> str | None:
    return f.key


_GEOD = None


def _geod():
    global _GEOD
    if _GEOD is None:
        from pyproj import Geod

        _GEOD = Geod(ellps="WGS84")
    return _GEOD


def _geom_delta(a: BaseGeometry, b: BaseGeometry) -> float:
    """Symmetric-difference geodesic area in m²."""
    try:
        sym = a.symmetric_difference(b)
        area, _ = _geod().geometry_area_perimeter(sym)
        return abs(float(area))
    except Exception:
        return 0.0


def _geoms_equal(a: BaseGeometry | None, b: BaseGeometry | None) -> bool:
    if a is None or b is None:
        return a is b
    try:
        return bool(a.equals_exact(b, GEOM_TOLERANCE_DEG) or a.equals(b))
    except Exception:
        return False


def diff_features(old: list[FeatureView], new: list[FeatureView]) -> DiffResult:
    result = DiffResult()
    old_by_key = {_key(f): f for f in old if _key(f)}
    new_by_key = {_key(f): f for f in new if _key(f)}

    for k, nf in new_by_key.items():
        of = old_by_key.get(k)
        if of is None:
            result.added.append(nf)
            continue
        geom_changed = not _geoms_equal(of.geometry, nf.geometry)
        class_changed = (of.classification or None) != (nf.classification or None)
        prop_diff = {
            kk: (of.properties.get(kk), nf.properties.get(kk))
            for kk in set(of.properties) | set(nf.properties)
            if of.properties.get(kk) != nf.properties.get(kk) and kk not in {"_transform_error"}
        }
        if geom_changed:
            delta = _geom_delta(of.geometry, nf.geometry) if of.geometry and nf.geometry else 0.0
            result.geometry_changed.append((of, nf, delta))
        if class_changed:
            result.classification_changed.append((of, nf))
        if prop_diff:
            result.properties_changed.append((of, nf, prop_diff))
        if not (geom_changed or class_changed or prop_diff):
            result.unchanged += 1
    for k, of in old_by_key.items():
        if k not in new_by_key:
            result.removed.append(of)
    return result


def load_layer_features(layer_id: uuid.UUID) -> list[FeatureView]:
    with session_scope() as s:
        rows = s.query(Feature).filter(Feature.layer_id == layer_id).all()
        out = []
        for r in rows:
            out.append(
                FeatureView(
                    id=str(r.id),
                    key=r.stable_external_id or r.source_object_code or str(r.id),
                    classification=r.classification,
                    geometry=to_shape(r.geometry) if r.geometry is not None else None,
                    properties=dict(r.properties or {}),
                )
            )
        return out


def compute_changeset(
    from_layer_id: uuid.UUID,
    to_layer_id: uuid.UUID,
    *,
    computed_by: str = "system",
) -> uuid.UUID:
    """Compute (or return cached) ChangeSet between two layers."""
    with session_scope() as s:
        existing = (
            s.query(ChangeSet)
            .filter_by(from_layer_id=from_layer_id, to_layer_id=to_layer_id)
            .one_or_none()
        )
        if existing:
            return existing.id

    old = load_layer_features(from_layer_id)
    new = load_layer_features(to_layer_id)
    diff = diff_features(old, new)

    # geometries are EPSG:4326 — use geodesic area, not raw degree²
    from pyproj import Geod

    geod = Geod(ellps="WGS84")

    def _m2(g) -> float:
        if g is None:
            return 0.0
        area, _ = geod.geometry_area_perimeter(g)
        return abs(area)

    summary = diff.summary()
    summary["added_area_m2"] = round(sum(_m2(f.geometry) for f in diff.added), 1)
    summary["removed_area_m2"] = round(sum(_m2(f.geometry) for f in diff.removed), 1)
    summary["modified_area_m2"] = round(sum(d for _, _, d in diff.geometry_changed), 1)

    with session_scope() as s:
        cs = ChangeSet(
            from_layer_id=from_layer_id,
            to_layer_id=to_layer_id,
            summary=summary,
            computed_by=computed_by,
        )
        s.add(cs)
        s.flush()

        def _entry(
            change_type, of: FeatureView | None, nf: FeatureView | None, delta=None, detail=None
        ):
            geom = None
            if of is not None and nf is not None and of.geometry and nf.geometry:
                try:
                    geom = of.geometry.symmetric_difference(nf.geometry)
                except Exception:
                    geom = None
            elif nf is not None:
                geom = nf.geometry
            elif of is not None:
                geom = of.geometry
            s.add(
                ChangeSetEntry(
                    change_set_id=cs.id,
                    change_type=change_type,
                    from_feature_id=uuid.UUID(of.id) if of else None,
                    to_feature_id=uuid.UUID(nf.id) if nf else None,
                    match_key=(nf.key if nf else of.key if of else None),
                    delta_area_m2=delta,
                    geometry=_to_postgis(geom) if geom is not None else None,
                    detail=detail or {},
                )
            )

        def _to_postgis(g):
            from openquyhoach_geo.geom import to_postgis

            return to_postgis(g)

        for f in diff.added:
            _entry("added", None, f)
        for f in diff.removed:
            _entry("removed", f, None)
        for of, nf, delta in diff.geometry_changed:
            _entry("geometry_changed", of, nf, delta=delta)
        for of, nf in diff.classification_changed:
            _entry(
                "classification_changed",
                of,
                nf,
                detail={"from": of.classification, "to": nf.classification},
            )
        for of, nf, props in diff.properties_changed:
            _entry("properties_changed", of, nf, detail={"diff": props})
        return cs.id
