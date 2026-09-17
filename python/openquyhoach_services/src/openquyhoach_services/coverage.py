"""Coverage summary — what OpenQuyHoach knows per administrative unit.

Crucially distinct from "does planning exist". A unit with
``no_source_discovered`` means we have not found a source, not that the
authority has published nothing.
"""

from __future__ import annotations

import uuid
from datetime import date

from openquyhoach_core.db import session_scope
from openquyhoach_core.models import (
    AdministrativeUnit,
    CoverageSummary,
    Dataset,
    Document,
    PlanningRecord,
    Source,
)
from sqlalchemy import func

STATE_ORDER = [
    "no_source_discovered",
    "source_discovered",
    "documents_indexed",
    "raster_available",
    "gis_available",
    "reviewed",
]


def recompute_coverage(admin_unit_id: uuid.UUID | None = None) -> int:
    """Recompute coverage summaries. Returns number of rows written."""
    with session_scope() as s:
        units = (
            [s.get(AdministrativeUnit, admin_unit_id)]
            if admin_unit_id
            else s.query(AdministrativeUnit).all()
        )
        count = 0
        for unit in units:
            if unit is None:
                continue
            # sources scoped to the unit's jurisdiction name
            src_count = (
                s.query(func.count(Source.id)).filter(Source.jurisdiction == unit.name).scalar()
                or 0
            )
            records = s.query(PlanningRecord).filter(PlanningRecord.admin_unit_id == unit.id).all()
            version_ids = [v.id for r in records for v in r.versions]
            doc_count = (
                s.query(func.count(Document.id))
                .filter(Document.planning_version_id.in_(version_ids or [uuid.uuid4()]))
                .scalar()
                or 0
            )
            datasets = (
                s.query(Dataset)
                .filter(Dataset.planning_version_id.in_(version_ids or [uuid.uuid4()]))
                .all()
            )
            has_raster = any(d.dataset_type == "raster" for d in datasets)
            has_gis = any(d.dataset_type == "vector" for d in datasets)
            reviewed = sum(1 for d in datasets if d.review_status == "approved")

            if reviewed:
                state = "reviewed"
            elif has_gis:
                state = "gis_available"
            elif has_raster:
                state = "raster_available"
            elif doc_count:
                state = "documents_indexed"
            elif src_count:
                state = "source_discovered"
            else:
                state = "no_source_discovered"

            row = s.query(CoverageSummary).filter_by(admin_unit_id=unit.id).one_or_none()
            if row is None:
                row = CoverageSummary(admin_unit_id=unit.id)
                s.add(row)
            row.state = state
            row.source_count = src_count
            row.document_count = doc_count
            row.dataset_count = len(datasets)
            row.reviewed_count = reviewed
            row.last_checked = date.today()
            count += 1
        return count
