"""Source descriptor schema validation."""

from __future__ import annotations

import pytest
import yaml
from openquyhoach_ingest.sources import (
    load_descriptor,
    to_config,
    validate_descriptor,
)

pytestmark = pytest.mark.unit

DEMO = "sources/demo"


def test_demo_descriptors_valid():
    for name in ("demo-district-v1", "demo-district-v2", "demo-district-docs"):
        issues = validate_descriptor(f"{DEMO}/{name}.yaml")
        assert issues == [], f"{name}: {[i.message for i in issues]}"


def test_to_config(tmp_path):
    data = load_descriptor(f"{DEMO}/demo-district-v1.yaml")
    cfg = to_config(data["key"], data)
    assert cfg.key == "demo/demo-district-v1"
    assert cfg.source_type == "file"
    assert cfg.parser["layer_map"]["quy_hoach_su_dung_dat"]["key_field"] == "ma_loai_dat"


def test_invalid_descriptor_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.dump({"key": "x"}))  # missing required fields
    issues = validate_descriptor(bad)
    assert issues, "schema must reject incomplete descriptors"

    worse = tmp_path / "worse.yaml"
    worse.write_text(yaml.dump({"key": "x", "source_type": "carrier_pigeon"}))
    assert validate_descriptor(worse)
