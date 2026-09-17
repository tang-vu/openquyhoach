"""Georeferencing endpoints — GCP editing, fitting, review gate."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from openquyhoach_core.errors import NotFoundError, ValidationError
from openquyhoach_services.georef_service import (
    create_job,
    get_job,
    list_jobs,
    review_job,
    update_gcps,
)
from pydantic import BaseModel, Field

from ..deps import AdminGuard

router = APIRouter(prefix="/v1/georef", tags=["georeferencing"])


@router.get("/jobs")
def jobs(status: str | None = None, limit: int = 50):
    return {"items": list_jobs(status=status, limit=limit)}


class CreateJobRequest(BaseModel):
    source_artifact_id: uuid.UUID
    transform_type: str = "affine"
    target_srid: int = 4326
    suggestion_source: str = "manual"
    dataset_id: uuid.UUID | None = None


@router.post("/jobs", dependencies=[AdminGuard])
def create(req: CreateJobRequest):
    job_id = create_job(
        req.source_artifact_id,
        transform_type=req.transform_type,
        target_srid=req.target_srid,
        suggestion_source=req.suggestion_source,
        dataset_id=req.dataset_id,
    )
    return {"job_id": str(job_id)}


@router.get("/jobs/{job_id}")
def job(job_id: uuid.UUID):
    out = get_job(job_id)
    if out is None:
        raise HTTPException(404, "georef job not found") from None
    return out


class GCPsRequest(BaseModel):
    gcps: list[dict] = Field(..., min_length=1)
    actor: str = "api"


@router.put("/jobs/{job_id}/gcps", dependencies=[AdminGuard])
def set_gcps(job_id: uuid.UUID, req: GCPsRequest):
    try:
        return update_gcps(job_id, req.gcps, actor=req.actor)
    except NotFoundError:
        raise HTTPException(404, "georef job not found") from None
    except ValidationError as exc:
        raise HTTPException(409, str(exc)) from exc


class ReviewRequest(BaseModel):
    approve: bool
    reviewer: str = Field(..., min_length=1)
    notes: str = ""


@router.post("/jobs/{job_id}/review", dependencies=[AdminGuard])
def review(job_id: uuid.UUID, req: ReviewRequest):
    try:
        status = review_job(job_id, approve=req.approve, reviewer=req.reviewer, notes=req.notes)
    except NotFoundError:
        raise HTTPException(404, "georef job not found") from None
    return {"job_id": str(job_id), "review_status": status}
