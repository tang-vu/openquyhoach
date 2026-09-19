"""Operational endpoints: source registry, crawl state, upstream changes,
coverage + freshness. Read-only — mutation paths live under admin auth."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from openquyhoach_core.db import session_scope
from openquyhoach_core.enums import ResourceStatus
from openquyhoach_core.models import (
    AdministrativeUnit,
    CoverageSummary,
    Dataset,
    Document,
    IngestionRun,
    PlanningRecord,
    PlanningVersion,
    ReviewTask,
    Source,
    SourceChangeEvent,
    SourceCrawlState,
    SourceObservation,
    SourceResource,
)
from sqlalchemy import func

from ..deps import PageDep
from ..serializers import iso, source_out

router = APIRouter(prefix="/v1", tags=["ops"])


def _freshness(st: SourceCrawlState | None, now: datetime) -> dict:
    if st is None or st.last_check_at is None:
        return {"freshness": "never_checked", "due": True}
    due = st.next_check_at is None or st.next_check_at <= now
    if st.last_success_at is None:
        return {"freshness": "never_succeeded", "due": True}
    return {"freshness": "overdue" if due else "fresh", "due": due}


def crawl_state_out(st: SourceCrawlState | None, now: datetime) -> dict:
    base = _freshness(st, now)
    if st is None:
        return {**base, "health": "unknown", "resources_seen": 0}
    return {
        **base,
        "health": st.health,
        "last_check_at": iso(st.last_check_at),
        "last_success_at": iso(st.last_success_at),
        "last_change_at": iso(st.last_change_at),
        "next_check_at": iso(st.next_check_at),
        "consecutive_failures": st.consecutive_failures,
        "resources_seen": st.resources_seen,
        "last_http_status": st.last_http_status,
        "last_error": (st.last_error or "")[:300] or None,
        "locked": bool(st.locked_until and st.locked_until > now),
    }


@router.get("/sources")
def list_sources(
    health: str | None = Query(None),
    enabled: bool | None = Query(None),
    jurisdiction: str | None = Query(None),
):
    now = datetime.now(UTC)
    with session_scope() as s:
        qy = (
            s.query(Source, SourceCrawlState)
            .outerjoin(SourceCrawlState, SourceCrawlState.source_id == Source.id)
            .order_by(Source.priority.asc(), Source.id.asc())
        )
        if enabled is not None:
            qy = qy.filter(Source.enabled.is_(enabled))
        if jurisdiction:
            qy = qy.filter(Source.jurisdiction == jurisdiction)
        if health:
            qy = qy.filter(SourceCrawlState.health == health)
        rows = qy.all()
        items = []
        for src, st in rows:
            out = source_out(src)
            out["crawl"] = crawl_state_out(st, now)
            items.append(out)
        return {"total": len(items), "items": items}


@router.get("/sources/{key:path}")
def get_source(key: str, observations: int = Query(20, le=200)):
    now = datetime.now(UTC)
    with session_scope() as s:
        src = s.query(Source).filter_by(source_key=key).one_or_none()
        if src is None:
            raise HTTPException(404, "source not found")
        st = s.query(SourceCrawlState).filter_by(source_id=src.id).one_or_none()
        resources = (
            s.query(SourceResource)
            .filter_by(source_id=src.id)
            .order_by(SourceResource.last_seen_at.desc())
            .limit(500)
            .all()
        )
        obs = (
            s.query(SourceObservation)
            .filter_by(source_id=src.id)
            .order_by(SourceObservation.observed_at.desc())
            .limit(observations)
            .all()
        )
        runs = (
            s.query(IngestionRun)
            .filter_by(source_id=src.id)
            .order_by(IngestionRun.started_at.desc())
            .limit(10)
            .all()
        )
        out = source_out(src)
        out["crawl"] = crawl_state_out(st, now)
        out["resources"] = [
            {
                "id": str(r.id),
                "key": r.resource_key,
                "url": r.url,
                "status": r.status,
                "title": r.title,
                "first_seen_at": iso(r.first_seen_at),
                "last_seen_at": iso(r.last_seen_at),
                "last_changed_at": iso(r.last_changed_at),
                "http_status": r.http_status,
                "content_sha256": r.content_sha256,
                "artifact_id": str(r.artifact_id) if r.artifact_id else None,
            }
            for r in resources
        ]
        out["recent_observations"] = [
            {
                "at": iso(o.observed_at),
                "outcome": o.outcome,
                "http_status": o.http_status,
                "sha256": o.content_sha256,
                "artifact_id": str(o.artifact_id) if o.artifact_id else None,
                "detail": o.detail,
            }
            for o in obs
        ]
        out["recent_runs"] = [
            {
                "id": str(r.id),
                "status": r.status,
                "trigger": r.trigger,
                "started_at": iso(r.started_at),
                "completed_at": iso(r.completed_at),
                "error": r.error_summary,
            }
            for r in runs
        ]
        return out


@router.get("/changes")
def list_changes(
    page: PageDep,
    source: str | None = Query(None),
    change_type: str | None = Query(None),
):
    with session_scope() as s:
        qy = (
            s.query(SourceChangeEvent, Source.source_key)
            .join(Source, Source.id == SourceChangeEvent.source_id)
            .order_by(SourceChangeEvent.detected_at.desc())
        )
        if source:
            qy = qy.filter(Source.source_key == source)
        if change_type:
            qy = qy.filter(SourceChangeEvent.change_type == change_type)
        total = qy.count()
        rows = qy.offset(page.offset).limit(page.limit).all()
        return {
            "total": total,
            "items": [
                {
                    "id": str(e.id),
                    "source": k,
                    "change_type": e.change_type,
                    "detected_at": iso(e.detected_at),
                    "resource_id": str(e.resource_id) if e.resource_id else None,
                    "run_id": str(e.run_id) if e.run_id else None,
                    "from_artifact_id": str(e.from_artifact_id) if e.from_artifact_id else None,
                    "to_artifact_id": str(e.to_artifact_id) if e.to_artifact_id else None,
                    "detail": e.detail,
                }
                for e, k in rows
            ],
        }


@router.get("/coverage/detail")
def coverage_detail(
    level: str | None = Query(None, description="admin level filter"),
    planning_type: str | None = Query(None),
    state: str | None = Query(None, description="coverage state filter"),
):
    """Per-jurisdiction coverage + freshness.

    Joins the materialized coverage summary with live crawl state and
    version statistics — "freshness" is the source-level answer, never a
    guess about whether planning exists."""
    now = datetime.now(UTC)
    with session_scope() as s:
        units_q = s.query(AdministrativeUnit)
        if level:
            units_q = units_q.filter(AdministrativeUnit.level == level)
        units = units_q.order_by(AdministrativeUnit.name).all()
        items = []
        for u in units:
            cov = s.query(CoverageSummary).filter_by(admin_unit_id=u.id).one_or_none()
            if state and (cov is None or cov.state != state):
                continue
            src_rows = (
                s.query(Source, SourceCrawlState)
                .outerjoin(SourceCrawlState, SourceCrawlState.source_id == Source.id)
                .filter((Source.admin_unit_id == u.id) | (Source.jurisdiction == u.name))
                .all()
            )
            last_success = max(
                (st.last_success_at for _src, st in src_rows if st and st.last_success_at),
                default=None,
            )
            last_change = max(
                (st.last_change_at for _src, st in src_rows if st and st.last_change_at),
                default=None,
            )
            healths = {st.health for _src, st in src_rows if st}
            due = any(
                st is None or st.next_check_at is None or st.next_check_at <= now
                for _src, st in src_rows
                if _src.enabled
            )
            records = s.query(PlanningRecord).filter_by(admin_unit_id=u.id).all()
            if planning_type:
                records = [r for r in records if r.planning_type == planning_type]
            version_ids = [v.id for r in records for v in r.versions]
            versions = (
                s.query(PlanningVersion)
                .filter(PlanningVersion.id.in_(version_ids or [uuid.uuid4()]))
                .all()
            )
            datasets = (
                s.query(Dataset)
                .filter(Dataset.planning_version_id.in_(version_ids or [uuid.uuid4()]))
                .all()
            )
            doc_ids = [
                d.id
                for d in s.query(Document.id)
                .filter(Document.planning_version_id.in_(version_ids or [uuid.uuid4()]))
                .all()
            ]
            doc_count = len(doc_ids)
            dataset_ids = [d.id for d in datasets]
            pending_reviews = (
                s.query(func.count(ReviewTask.id))
                .filter(
                    ReviewTask.status == "pending",
                    (
                        (ReviewTask.target_type == "dataset")
                        & ReviewTask.target_id.in_(dataset_ids or [uuid.uuid4()])
                    )
                    | (
                        (ReviewTask.target_type == "document")
                        & ReviewTask.target_id.in_(doc_ids or [uuid.uuid4()])
                    ),
                )
                .scalar()
                or 0
            )
            official = sum(
                1 for d in datasets if d.derivation_level.startswith("official")
            )
            eff_dates = [v.effective_from for v in versions if v.effective_from]
            earliest = min(eff_dates) if eff_dates else None
            latest = max(eff_dates) if eff_dates else None
            items.append(
                {
                    "unit": {
                        "id": str(u.id),
                        "name": u.name,
                        "official_code": u.official_code,
                        "level": u.level,
                    },
                    "coverage_state": cov.state if cov else "no_source_discovered",
                    "sources": len(src_rows),
                    "source_health": sorted(healths),
                    "freshness": {
                        "last_successful_check": iso(last_success),
                        "last_detected_change": iso(last_change),
                        "due_for_check": due and bool(src_rows),
                    },
                    "records": len(records),
                    "versions": len(versions),
                    "earliest_version": str(earliest) if earliest else None,
                    "latest_version": str(latest) if latest else None,
                    "datasets": len(datasets),
                    "vector_datasets": sum(1 for d in datasets if d.dataset_type == "vector"),
                    "raster_datasets": sum(1 for d in datasets if d.dataset_type == "raster"),
                    "documents": doc_count,
                    "official_datasets": official,
                    "derived_datasets": len(datasets) - official,
                    "pending_review_tasks": pending_reviews,
                }
            )
        return {"total": len(items), "items": items}
