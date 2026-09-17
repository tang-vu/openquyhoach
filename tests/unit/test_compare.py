"""Feature diffing — pure shapely/pyproj, no DB."""

from __future__ import annotations

import pytest
from openquyhoach_services.compare import FeatureView, diff_features
from shapely.geometry import box

pytestmark = pytest.mark.unit


def fv(key, geom=None, cls=None, props=None, fid=None):
    return FeatureView(
        id=fid or key or "x",
        key=key,
        classification=cls,
        geometry=geom,
        properties=props or {},
    )


def test_added_removed():
    old = [fv("A", box(105, 20, 105.01, 20.01))]
    new = [fv("B", box(105, 20, 105.01, 20.01))]
    r = diff_features(old, new)
    assert r.summary()["added"] == 1
    assert r.summary()["removed"] == 1


def test_geometry_change_area_m2():
    a = box(105.0, 20.0, 105.01, 20.01)
    b = box(105.0, 20.0, 105.02, 20.01)  # ~1km wider strip
    r = diff_features([fv("A", a)], [fv("A", b)])
    assert r.summary()["geometry_changed"] == 1
    _, _, delta = r.geometry_changed[0]
    # ~0.01° x 0.01° at lat 20 ≈ 1.1e6 m² — must be metres, not degrees
    assert delta > 1e5
    assert delta < 1e8


def test_classification_and_props():
    a = box(105, 20, 105.01, 20.01)
    old = [fv("A", a, cls="ODT", props={"area": 10})]
    new = [fv("A", a, cls="CAY", props={"area": 11})]
    r = diff_features(old, new)
    assert r.summary()["classification_changed"] == 1
    assert r.summary()["properties_changed"] == 1
    assert r.properties_changed[0][2] == {"area": (10, 11)}
    assert r.summary()["unchanged"] == 0


def test_unchanged():
    a = box(105, 20, 105.01, 20.01)
    r = diff_features([fv("A", a, props={"x": 1})], [fv("A", a, props={"x": 1})])
    assert r.summary()["unchanged"] == 1


def test_keyless_features_ignored_for_matching():
    # features without keys must not silently merge/match
    r = diff_features([fv(None)], [fv(None)])
    assert r.summary()["unchanged"] == 0


def test_transform_error_prop_not_diffed():
    a = box(105, 20, 105.01, 20.01)
    old = [fv("A", a, props={})]
    new = [fv("A", a, props={"_transform_error": "crs"})]
    r = diff_features(old, new)
    assert r.summary()["properties_changed"] == 0
    assert r.summary()["unchanged"] == 1
