"""Pipeline helpers — _jsonb_safe + _extract_jsvar_geojson (pure functions)."""

from __future__ import annotations

import json
import math
from typing import ClassVar

import pytest
from openquyhoach_ingest.pipeline import _extract_jsvar_geojson, _jsonb_safe

pytestmark = pytest.mark.unit


class TestJsonbSafe:
    def test_nan_and_inf_become_none(self):
        out = _jsonb_safe({"a": float("nan"), "b": float("inf"), "c": -float("inf")})
        assert out == {"a": None, "b": None, "c": None}

    def test_nested_structures(self):
        src = {
            "props": {"vals": [1.5, float("nan"), {"deep": float("inf")}]},
            "name": "x",
            "n": 3,
        }
        out = _jsonb_safe(src)
        assert out["props"]["vals"][0] == 1.5
        assert out["props"]["vals"][1] is None
        assert out["props"]["vals"][2]["deep"] is None
        assert out["name"] == "x" and out["n"] == 3

    def test_serializes_to_strict_json(self):
        out = _jsonb_safe({"v": [float("nan"), 1]})
        # strict json.dumps (allow_nan=False, the JSONB-safe check) must pass
        json.dumps(out, allow_nan=False)

    def test_passthrough(self):
        assert _jsonb_safe("s") == "s"
        assert _jsonb_safe(None) is None
        assert _jsonb_safe(1.5) == 1.5
        assert not math.isnan(_jsonb_safe(2.0) or 0)


class TestExtractJsvarGeojson:
    FC: ClassVar[dict] = {"type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {},
                      "geometry": {"type": "Point", "coordinates": [1, 2]}}]}

    def test_valid_var_wrapper(self, tmp_path):
        p = tmp_path / "qhpk.js"
        p.write_text(f"var qhpk = {json.dumps(self.FC)};", encoding="utf-8")
        out = _extract_jsvar_geojson(p)
        assert out is not None and out.exists()
        assert json.loads(out.read_text())["type"] == "FeatureCollection"

    def test_whitespace_and_no_semicolon(self, tmp_path):
        p = tmp_path / "x.js"
        p.write_text(f"\n\nvar $l_1 =\n{json.dumps(self.FC)}\n", encoding="utf-8")
        assert _extract_jsvar_geojson(p) is not None

    def test_rejects_non_var(self, tmp_path):
        p = tmp_path / "a.js"
        p.write_text('alert("x")', encoding="utf-8")
        assert _extract_jsvar_geojson(p) is None

    def test_rejects_non_fc_json(self, tmp_path):
        p = tmp_path / "a.js"
        p.write_text("var x = {\"type\": \"Feature\"};", encoding="utf-8")
        assert _extract_jsvar_geojson(p) is None

    def test_rejects_features_not_list(self, tmp_path):
        p = tmp_path / "a.js"
        p.write_text('var x = {"type":"FeatureCollection","features":{}};',
                     encoding="utf-8")
        assert _extract_jsvar_geojson(p) is None

    def test_rejects_invalid_json(self, tmp_path):
        p = tmp_path / "a.js"
        p.write_text("var x = {not json};", encoding="utf-8")
        assert _extract_jsvar_geojson(p) is None

    def test_missing_file(self, tmp_path):
        assert _extract_jsvar_geojson(tmp_path / "nope.js") is None
