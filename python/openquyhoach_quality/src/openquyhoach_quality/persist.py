"""Persist findings as quality_observations and update dataset state."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from openquyhoach_core.enums import QualitySeverity
from openquyhoach_core.models import Dataset, QualityObservation
from openquyhoach_geo.geom import to_postgis
from sqlalchemy import update
from sqlalchemy.orm import Session

from .engine import Finding, summarize


def persist_findings(
    session: Session,
    findings: list[Finding],
    *,
    dataset_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    feature_id_map: dict[str, uuid.UUID] | None = None,
    layer_id_map: dict[str, uuid.UUID] | None = None,
) -> int:
    """Write findings; replaces unresolved observations from prior runs."""
    session.execute(
        update(QualityObservation)
        .where(
            QualityObservation.target_type == "dataset",
            QualityObservation.target_id == dataset_id,
            QualityObservation.resolved_at.is_(None),
        )
        .values(resolved_at=datetime.now(UTC), resolution="superseded by new run")
    )
    fid_map = feature_id_map or {}
    lid_map = layer_id_map or {}
    count = 0
    for f in findings:
        target_id = dataset_id
        target_type = f.target_type
        if f.target_type == "feature" and f.target_ref and f.target_ref in fid_map:
            target_id = fid_map[f.target_ref]
        elif f.target_type == "layer" and f.target_ref and f.target_ref in lid_map:
            target_id = lid_map[f.target_ref]
        else:
            target_type = "dataset"
        geom = None
        if f.geometry_wkt:
            try:
                import shapely.wkt

                geom = to_postgis(shapely.wkt.loads(f.geometry_wkt))
            except Exception:
                geom = None
        session.add(
            QualityObservation(
                target_type=target_type,
                target_id=target_id,
                run_id=run_id,
                rule_code=f.rule_code,
                severity=f.severity,
                message=f.message[:4000],
                geometry=geom,
                evidence=f.evidence,
            )
        )
        count += 1

    s = summarize(findings)
    state = (
        "errors"
        if s["by_severity"].get(QualitySeverity.ERROR.value)
        or s["by_severity"].get(QualitySeverity.CRITICAL.value)
        else "warnings"
        if s["total"]
        else "clean"
    )
    ds = session.get(Dataset, dataset_id)
    if ds is not None:
        ds.quality_state = state
    return count
