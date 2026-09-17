"""Ingestion + source-registry + review-queue endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from openquyhoach_core.db import session_scope
from openquyhoach_core.enums import ProvenanceOp
from openquyhoach_core.models import IngestionRun, ReviewTask, Source
from openquyhoach_core.provenance import record_event
from openquyhoach_core.queue import get_queue
from openquyhoach_ingest.sources import sync_sources, validate_all
from pydantic import BaseModel, Field

from ..deps import AdminGuard, PageDep
from ..serializers import run_out, source_out, task_out

router = APIRouter(prefix="/v1", tags=["ingest"])


@router.get("/sources")
def list_sources(page: PageDep, enabled: bool | None = None):
    with session_scope() as s:
        qy = s.query(Source)
        if enabled is not None:
            qy = qy.filter(Source.enabled == enabled)
        return {
            "total": qy.count(),
            "items": [
                source_out(r)
                for r in qy.order_by(Source.source_key).offset(page.offset).limit(page.limit).all()
            ],
        }


@router.get("/sources/validate")
def sources_validate():
    issues = validate_all()
    return {
        "ok": not issues,
        "issues": [{"path": i.path, "message": i.message} for i in issues],
    }


@router.post("/sources/sync", dependencies=[AdminGuard])
def sources_sync():
    return sync_sources()


class IngestRequest(BaseModel):
    source_key: str | None = None
    url: str | None = None
    dry_run: bool = False
    async_: bool = Field(False, alias="async")


@router.post("/ingest/run", dependencies=[AdminGuard])
def ingest_run(req: IngestRequest):
    """Trigger an ingestion run — inline or via the configured queue."""
    if not req.source_key and not req.url:
        raise HTTPException(400, "provide source_key or url")
    if req.async_:
        q = get_queue()
        if req.url:
            job = q.enqueue(
                "ingest_url", url=req.url, source_key=req.source_key, dry_run=req.dry_run
            )
        else:
            job = q.enqueue("ingest_source", source_key=req.source_key, dry_run=req.dry_run)
        return {"job_id": job, "queued": True}
    if req.url:
        from openquyhoach_ingest.pipeline import ingest_url

        run_id = ingest_url(req.url, source_key=req.source_key, dry_run=req.dry_run)
    else:
        assert req.source_key is not None  # guarded above
        from openquyhoach_ingest.pipeline import ingest_source

        run_id = ingest_source(req.source_key, dry_run=req.dry_run)
    return {"run_id": str(run_id), "queued": False}


@router.get("/ingest/runs")
def list_runs(page: PageDep, status: str | None = None):
    with session_scope() as s:
        qy = s.query(IngestionRun)
        if status:
            qy = qy.filter(IngestionRun.status == status)
        total = qy.count()
        rows = (
            qy.order_by(IngestionRun.started_at.desc()).offset(page.offset).limit(page.limit).all()
        )
        return {"total": total, "items": [run_out(r) for r in rows]}


@router.get("/ingest/runs/{run_id}")
def get_run(run_id: uuid.UUID):
    from openquyhoach_core.models import ProvenanceEvent

    with session_scope() as s:
        r = s.get(IngestionRun, run_id)
        if r is None:
            raise HTTPException(404, "run not found")
        out = run_out(r)
        out["events"] = [
            {
                "operation": e.operation,
                "entity": f"{e.entity_type}:{e.entity_id}",
                "tool": e.tool,
                "actor": e.actor,
                "at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in s.query(ProvenanceEvent)
            .filter_by(run_id=r.id)
            .order_by(ProvenanceEvent.created_at)
            .limit(500)
            .all()
        ]
        return out


@router.get("/review/tasks")
def review_tasks(page: PageDep, status: str = "pending", task_type: str | None = None):
    with session_scope() as s:
        qy = s.query(ReviewTask).filter(ReviewTask.status == status)
        if task_type:
            qy = qy.filter(ReviewTask.task_type == task_type)
        total = qy.count()
        rows = (
            qy.order_by(ReviewTask.priority, ReviewTask.created_at)
            .offset(page.offset)
            .limit(page.limit)
            .all()
        )
        return {"total": total, "items": [task_out(t) for t in rows]}


class ResolveRequest(BaseModel):
    resolution: str = Field(..., min_length=2)
    reviewer: str = Field(..., min_length=1)
    approve: bool = True


@router.post("/review/tasks/{task_id}/resolve", dependencies=[AdminGuard])
def resolve_task(task_id: uuid.UUID, req: ResolveRequest):
    with session_scope() as s:
        t = s.get(ReviewTask, task_id)
        if t is None:
            raise HTTPException(404, "task not found")
        if t.status != "pending":
            raise HTTPException(409, f"task already {t.status}")
        t.status = "done" if req.approve else "dismissed"
        t.resolution = req.resolution
        t.reviewer = req.reviewer
        t.reviewed_at = datetime.now(UTC)
        record_event(
            s,
            entity_type=t.target_type,
            entity_id=t.target_id,
            operation=ProvenanceOp.HUMAN_REVIEWED,
            parameters={"task": t.task_type, "approved": req.approve, "resolution": req.resolution},
            actor=req.reviewer,
            actor_type="human",
        )
        return task_out(t)
