"""Quality rules — pure shapely, no DB."""

from __future__ import annotations

import pytest
from openquyhoach_quality.engine import (
    FeaturePayload,
    LayerPayload,
    ValidationContext,
    rule_catalog,
    run_rules,
    summarize,
)
from shapely.geometry import LineString, Point, Polygon, box

pytestmark = pytest.mark.unit


def ctx(layers, **kw) -> ValidationContext:
    meta = {"authority": "test", "has_provenance": True}
    meta.update(kw.pop("meta", {}))
    return ValidationContext(
        dataset_group="quy_hoach",
        dataset_type="vector",
        derivation_level="official_vector",
        original_crs={"epsg": 4326, "identified": True},
        layers=layers,
        meta=meta,
        **kw,
    )


def poly(x0=0, y0=0, x1=1, y1=1):
    return box(x0, y0, x1, y1)


def fp(key, geom, props=None):
    return FeaturePayload(key=key, geometry=geom, properties=props or {})


class TestGeometryRules:
    def test_empty_geom(self):
        c = ctx([LayerPayload("l", "Polygon", None, [fp("a", Polygon())])])
        codes = {f.rule_code for f in run_rules(c)}
        assert "QH-GEOM-EMPTY" in codes

    def test_invalid_geom(self):
        bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2)])
        c = ctx([LayerPayload("l", "Polygon", None, [fp("a", bowtie)])])
        codes = {f.rule_code for f in run_rules(c)}
        assert "QH-GEOM-INVALID" in codes

    def test_overlap_detected(self):
        a, b = poly(0, 0, 2, 2), poly(1, 1, 3, 3)
        c = ctx(
            [LayerPayload("l", "Polygon", "Polygon", [fp("a", a), fp("b", b)])],
            required_attributes={},
            meta={
                "authority": "t",
                "has_provenance": True,
                "topology": {"l": {"no_overlap": True}},
            },
        )
        findings = run_rules(c)
        assert any(f.rule_code == "QH-TOPO-POLY-OVERLAP" for f in findings)

    def test_overlap_not_checked_without_flag(self):
        a, b = poly(0, 0, 2, 2), poly(1, 1, 3, 3)
        c = ctx([LayerPayload("l", "Polygon", "Polygon", [fp("a", a), fp("b", b)])])
        findings = run_rules(c)
        assert not any(f.rule_code == "QH-TOPO-POLY-OVERLAP" for f in findings)

    def test_type_mismatch(self):
        c = ctx([LayerPayload("l", "Polygon", "Polygon", [fp("a", LineString([(0, 0), (1, 1)]))])])
        assert any(f.rule_code == "QH-GEOM-TYPE-MISMATCH" for f in run_rules(c))

    def test_bounds_vietnam(self):
        far = Point(0.0, 0.0)  # Gulf of Guinea — far outside VN bounds
        c = ctx([LayerPayload("l", "Point", None, [fp("a", far)])])
        assert any(f.rule_code == "QH-CRS-BOUNDS" for f in run_rules(c))

    def test_clean_layer_minimal_findings(self):
        c = ctx(
            [LayerPayload("l", "Polygon", "Polygon", [fp("a", poly(0, 0, 1, 1), {"code": "x"})])]
        )
        findings = run_rules(c)
        assert summarize(findings)["has_errors"] is False


class TestMetaRules:
    def test_missing_required_attr(self):
        c = ctx(
            [LayerPayload("l", "Polygon", "Polygon", [fp("a", poly())])],
            required_attributes={"l": ["ma_loai_dat"]},
        )
        codes = {f.rule_code for f in run_rules(c)}
        assert any("ATTR" in code for code in codes)

    def test_unidentified_crs_critical(self):
        c = ValidationContext(
            dataset_type="vector",
            original_crs={"identified": False},
            layers=[LayerPayload("l", "Polygon", None, [fp("a", poly())])],
            meta={"authority": "t", "has_provenance": True},
        )
        findings = run_rules(c)
        assert any(f.rule_code == "QH-CRS-MISSING" and f.severity == "critical" for f in findings)


class TestCatalog:
    def test_catalog_nonempty_stable(self):
        cat = rule_catalog()
        assert len(cat) >= 8
        assert all(k.startswith("QH-") for k in cat)

    def test_crashing_rule_becomes_finding(self):
        from openquyhoach_quality.engine import rule

        @rule("QH-TEST-BOOM", "explodes", "error")
        def _boom(c):
            raise RuntimeError("boom")
            yield  # pragma: no cover

        try:
            findings = run_rules(ctx([LayerPayload("l", None, None, [])]))
            assert any(f.rule_code == "QH-RULE-ERROR" for f in findings)
        finally:
            from openquyhoach_quality.engine import _REGISTRY

            _REGISTRY.pop("QH-TEST-BOOM", None)
