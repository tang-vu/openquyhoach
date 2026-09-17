"""GeoreferenceJob persistence + compute + review-gate service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from openquyhoach_core.db import session_scope
from openquyhoach_core.enums import GeorefStatus, ProvenanceOp, ReviewStatus
from openquyhoach_core.errors import NotFoundError, ValidationError
from openquyhoach_core.models import Dataset, GeoreferenceJob
from openquyhoach_core.provenance import record_event
from openquyhoach_geo.georef import compute_transform


def create_job(
    artifact_id: uuid.UUID,
    *,
    transform_type: str = "affine",
    target_srid: int = 4326,
    suggestion_source: str = "manual",
    dataset_id: uuid.UUID | None = None,
) -> uuid.UUID:
    with session_scope() as s:
        job = GeoreferenceJob(
            source_artifact_id=artifact_id,
            dataset_id=dataset_id,
            transform_type=transform_type,
            target_srid=target_srid,
            suggestion_source=suggestion_source,
            review_status=GeorefStatus.DRAFT.value,
        )
        s.add(job)
        s.flush()
        record_event(
            s,
            entity_type="georef_job",
            entity_id=job.id,
            operation="created",
            parameters={"transform": transform_type},
        )
        return job.id


def update_gcps(job_id: uuid.UUID, gcps: list[dict], *, actor: str = "manual") -> dict:
    """Save draft GCPs and recompute transform + residuals."""
    with session_scope() as s:
        job = s.get(GeoreferenceJob, job_id)
        if job is None:
            raise NotFoundError(f"georef job {job_id}")
        if job.review_status == GeorefStatus.APPROVED.value:
            raise ValidationError("job already approved — create a new revision")
        job.gcps = gcps
        try:
            result = compute_transform(gcps, transform_type=job.transform_type)
            job.transform_coefficients = result.coefficients
            job.rmse = result.rmse
            job.residuals = result.residuals
            job.review_status = GeorefStatus.COMPUTED.value
            job.algorithm = f"least-squares+ransac/{job.transform_type}"
        except ValueError as exc:
            job.review_status = GeorefStatus.DRAFT.value
            job.notes = str(exc)
            result = None
        record_event(
            s,
            entity_type="georef_job",
            entity_id=job.id,
            operation=ProvenanceOp.GEOREFERENCED,
            parameters={"gcp_count": len(gcps), "rmse": result.rmse if result else None},
            actor=actor,
            actor_type="human",
        )
        return {
            "rmse": result.rmse if result else None,
            "residuals": result.residuals if result else {},
            "rejected": result.rejected if result else [],
            "status": job.review_status,
        }


def review_job(job_id: uuid.UUID, *, approve: bool, reviewer: str, notes: str = "") -> str:
    with session_scope() as s:
        job = s.get(GeoreferenceJob, job_id)
        if job is None:
            raise NotFoundError(f"georef job {job_id}")
        job.review_status = GeorefStatus.APPROVED.value if approve else GeorefStatus.REJECTED.value
        job.reviewer = reviewer
        job.reviewed_at = datetime.now(UTC)
        job.notes = notes or job.notes
        if job.dataset_id:
            ds = s.get(Dataset, job.dataset_id)
            if ds is not None:
                ds.review_status = (
                    ReviewStatus.APPROVED.value if approve else ReviewStatus.REJECTED.value
                )
        record_event(
            s,
            entity_type="georef_job",
            entity_id=job.id,
            operation=ProvenanceOp.HUMAN_REVIEWED,
            parameters={"approved": approve},
            actor=reviewer,
            actor_type="human",
        )
        return job.review_status


def get_job(job_id: uuid.UUID) -> dict | None:
    with session_scope() as s:
        j = s.get(GeoreferenceJob, job_id)
        if j is None:
            return None
        return {
            "id": str(j.id),
            "source_artifact_id": str(j.source_artifact_id),
            "dataset_id": str(j.dataset_id) if j.dataset_id else None,
            "transform_type": j.transform_type,
            "target_srid": j.target_srid,
            "gcps": j.gcps,
            "suggestions": j.suggestions,
            "rmse": j.rmse,
            "residuals": j.residuals,
            "review_status": j.review_status,
            "suggestion_source": j.suggestion_source,
            "output_storage_key": j.output_storage_key,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        }


def list_jobs(status: str | None = None, limit: int = 50) -> list[dict]:
    with session_scope() as s:
        q = s.query(GeoreferenceJob).order_by(GeoreferenceJob.created_at.desc()).limit(limit)
        if status:
            q = q.filter(GeoreferenceJob.review_status == status)
        return [
            {
                "id": str(j.id),
                "rmse": j.rmse,
                "review_status": j.review_status,
                "transform_type": j.transform_type,
                "gcp_count": len(j.gcps or []),
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in q.all()
        ]
