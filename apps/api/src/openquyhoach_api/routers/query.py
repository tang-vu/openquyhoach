"""Query endpoints: search, point-query (the "what is planned here" API),
provenance graph, coverage."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from openquyhoach_core.db import get_engine, session_scope
from openquyhoach_core.models import CoverageSummary
from openquyhoach_services.provenance_service import (
    provenance_graph,
    provenance_summary_for_feature,
)
from openquyhoach_services.search import search as do_search
from sqlalchemy import text

from ..deps import PageDep

router = APIRouter(prefix="/v1", tags=["query"])


@router.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = Query(10, le=50)):
    return {"results": [vars(r) for r in do_search(q, limit=limit)]}


@router.get("/features/query")
def point_query(
    lon: float = Query(..., ge=-180, le=180),
    lat: float = Query(..., ge=-90, le=90),
    buffer_m: float = Query(50.0, ge=0, le=5000),
    limit: int = Query(50, ge=1, le=500),
):
    """ "What is planned at this point?" — every hit carries provenance."""
    sql = text(
        """
        SELECT f.id, l.canonical_name AS layer, d.id AS dataset_id,
               d.derivation_level, d.review_status,
               f.classification, f.properties,
               ST_Distance(
                 ST_Transform(f.geometry, 3857),
                 ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 3857)
               ) AS dist_m
        FROM features f
        JOIN layers l ON l.id = f.layer_id
        JOIN datasets d ON d.id = l.dataset_id
        WHERE d.published
          AND ST_DWithin(
            ST_Transform(f.geometry, 3857),
            ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 3857),
            :buf)
        ORDER BY dist_m
        LIMIT :lim
        """
    )
    with get_engine().connect() as conn:
        rows = (
            conn.execute(sql, {"lon": lon, "lat": lat, "buf": buffer_m, "lim": limit})
            .mappings()
            .all()
        )
    hits = []
    for r in rows:
        hits.append(
            {
                "feature_id": str(r["id"]),
                "layer": r["layer"],
                "dataset_id": str(r["dataset_id"]),
                "derivation_level": r["derivation_level"],
                "review_status": r["review_status"],
                "classification": r["classification"],
                "properties": r["properties"],
                "distance_m": round(float(r["dist_m"]), 2),
                "provenance": provenance_summary_for_feature(r["id"]),
            }
        )
    return {"lon": lon, "lat": lat, "buffer_m": buffer_m, "hits": hits}


@router.get("/provenance/{entity_type}/{entity_id}")
def provenance(entity_type: str, entity_id: uuid.UUID):
    allowed = {
        "artifact",
        "document",
        "dataset",
        "layer",
        "feature",
        "georef_job",
        "publication",
        "planning_version",
        "source",
    }
    if entity_type not in allowed:
        raise HTTPException(400, f"entity_type must be one of {sorted(allowed)}")
    return provenance_graph(entity_type, entity_id)


@router.get("/coverage")
def coverage(page: PageDep, state: str | None = None):
    """Coverage summary rows enriched with live source freshness/health —
    'no source discovered' stays distinct from 'no planning exists'."""
    from datetime import UTC, datetime

    from openquyhoach_core.models import Source, SourceCrawlState

    now = datetime.now(UTC)
    with session_scope() as s:
        qy = s.query(CoverageSummary)
        if state:
            qy = qy.filter(CoverageSummary.state == state)
        total = qy.count()
        rows = qy.offset(page.offset).limit(page.limit).all()
        items = []
        for c in rows:
            src_rows = (
                s.query(SourceCrawlState)
                .join(Source, Source.id == SourceCrawlState.source_id)
                .filter(Source.admin_unit_id == c.admin_unit_id)
                .all()
            )
            last_success = max(
                (st.last_success_at for st in src_rows if st.last_success_at),
                default=None,
            )
            last_change = max(
                (st.last_change_at for st in src_rows if st.last_change_at),
                default=None,
            )
            items.append(
                {
                    "admin_unit_id": str(c.admin_unit_id),
                    "state": c.state,
                    "source_count": c.source_count,
                    "document_count": c.document_count,
                    "dataset_count": c.dataset_count,
                    "reviewed_count": c.reviewed_count,
                    "last_checked": str(c.last_checked) if c.last_checked else None,
                    "freshness": {
                        "last_successful_check": str(last_success) if last_success else None,
                        "last_detected_change": str(last_change) if last_change else None,
                        "source_health": sorted({st.health for st in src_rows if st.health}),
                        "due_for_check": any(
                            st.next_check_at is None or st.next_check_at <= now
                            for st in src_rows
                        ),
                    },
                }
            )
        return {"total": total, "items": items}
