"""Published dataset manifest schema (docs/data-model + spec section 40)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

MANIFEST_SCHEMA_VERSION = "oqh.manifest/1"


class ManifestSource(BaseModel):
    authority: str | None = None
    source_key: str | None = None
    canonical_url: str | None = None
    artifact_sha256: str | None = None
    retrieved_at: datetime | None = None
    rights_statement: str | None = None
    license: str | None = None


class ManifestDataset(BaseModel):
    dataset_id: str
    name: str | None = None
    dataset_group: str
    dataset_type: str
    derivation_level: str
    review_status: str
    layer_count: int = 0
    feature_count: int = 0


class ManifestQuality(BaseModel):
    open_observations: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    rule_codes: list[str] = Field(default_factory=list)


class DataManifest(BaseModel):
    """Machine-readable manifest for a published planning version.
    Designed for future signing — keep it deterministic (sorted keys)."""

    schema_version: str = MANIFEST_SCHEMA_VERSION
    planning_record: str
    planning_record_title: str | None = None
    planning_version: str
    version_label: str | None = None
    authority: str | None = None
    legal_status: str
    approval_decision_number: str | None = None
    approval_date: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    sources: list[ManifestSource] = Field(default_factory=list)
    datasets: list[ManifestDataset] = Field(default_factory=list)
    derivation_level: str  # worst (least authoritative) level present
    quality: ManifestQuality = Field(default_factory=ManifestQuality)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    bbox: list[float] | None = None
    pmtiles_sha256: str | None = None
    published_at: datetime | None = None
    software_commit: str | None = None
    disclaimer: str = (
        "OpenQuyHoach is research/information infrastructure. This manifest does not "
        "certify legal validity; confirm with the responsible authority."
    )
