"""Experimental MCP server — read-only tools over the services layer.

Deliberately read-only: agents can *query* data and provenance but must
never mutate records or bypass review. Optional component; the core system
runs without it.
"""

from __future__ import annotations

import uuid

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("openquyhoach")


@mcp.tool()
def search_planning(q: str, limit: int = 10) -> list[dict]:
    """Search planning records, administrative units and decision documents
    by free text (Vietnamese diacritics-insensitive)."""
    from openquyhoach_services.search import search

    return [vars(r) for r in search(q, limit=limit)]


@mcp.tool()
def point_query(lon: float, lat: float, buffer_m: float = 50.0) -> dict:
    """ "What is planned at this coordinate?" — returns features with full
    provenance (source artifact checksum, planning version, review status)."""
    from openquyhoach_core.db import get_engine
    from sqlalchemy import text

    sql = text(
        """
        SELECT f.id, l.canonical_name AS layer, d.derivation_level,
               f.classification
        FROM features f
        JOIN layers l ON l.id = f.layer_id
        JOIN datasets d ON d.id = l.dataset_id
        WHERE d.published
          AND ST_DWithin(
            ST_Transform(f.geometry, 3857),
            ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 3857),
            :buf)
        LIMIT 50
        """
    )
    with get_engine().connect() as conn:
        rows = conn.execute(sql, {"lon": lon, "lat": lat, "buf": buffer_m}).mappings().all()
    from openquyhoach_services.provenance_service import (
        provenance_summary_for_feature,
    )

    return {
        "hits": [
            {
                **dict(r),
                "feature_id": str(r["id"]),
                "provenance": provenance_summary_for_feature(r["id"]),
            }
            for r in rows
        ]
    }


@mcp.tool()
def provenance_of(entity_type: str, entity_id: str) -> dict:
    """Full provenance DAG for an entity — every input artifact with
    checksums, tools, and review events. entity_type ∈
    artifact|document|dataset|layer|feature|georef_job|publication|
    planning_version|source."""
    from openquyhoach_services.provenance_service import provenance_graph

    return provenance_graph(entity_type, uuid.UUID(entity_id))


@mcp.tool()
def coverage() -> dict:
    """Coverage summary per administrative unit — distinguishes
    'no source discovered' from 'no planning exists'."""
    from openquyhoach_core.db import session_scope
    from openquyhoach_core.models import CoverageSummary

    with session_scope() as s:
        return {
            "items": [
                {
                    "admin_unit_id": str(c.admin_unit_id),
                    "state": c.state,
                    "dataset_count": c.dataset_count,
                    "reviewed_count": c.reviewed_count,
                }
                for c in s.query(CoverageSummary).all()
            ]
        }


@mcp.tool()
def source_status(key: str | None = None) -> dict:
    """Source registry + crawl health: last check/success/change times,
    consecutive failures, next scheduled check, resource counts. `key`
    filters to one source; omit for all."""
    from datetime import UTC, datetime

    from openquyhoach_core.db import session_scope
    from openquyhoach_core.models import Source, SourceCrawlState

    now = datetime.now(UTC)
    with session_scope() as s:
        qy = (
            s.query(Source, SourceCrawlState)
            .outerjoin(SourceCrawlState, SourceCrawlState.source_id == Source.id)
            .order_by(Source.id)
        )
        if key:
            qy = qy.filter(Source.source_key == key)
        items = []
        for src, st in qy.all():
            items.append(
                {
                    "key": src.source_key,
                    "name": src.name,
                    "authority": src.authority,
                    "jurisdiction": src.jurisdiction,
                    "source_type": src.source_type,
                    "enabled": src.enabled,
                    "health": st.health if st else "unknown",
                    "last_check_at": str(st.last_check_at) if st and st.last_check_at else None,
                    "last_success_at": str(st.last_success_at) if st and st.last_success_at else None,
                    "last_change_at": str(st.last_change_at) if st and st.last_change_at else None,
                    "next_check_at": str(st.next_check_at) if st and st.next_check_at else None,
                    "consecutive_failures": st.consecutive_failures if st else 0,
                    "resources_seen": st.resources_seen if st else 0,
                    "due": bool(st is None or st.next_check_at is None or st.next_check_at <= now),
                }
            )
        return {"total": len(items), "items": items}


@mcp.tool()
def recent_changes(limit: int = 25, source: str | None = None) -> dict:
    """Upstream change events: resources added, disappeared, reappeared,
    checksum-changed, url-changed, metadata-changed — with artifact links."""
    from openquyhoach_core.db import session_scope
    from openquyhoach_core.models import Source, SourceChangeEvent

    with session_scope() as s:
        qy = (
            s.query(SourceChangeEvent, Source.source_key)
            .join(Source, Source.id == SourceChangeEvent.source_id)
            .order_by(SourceChangeEvent.detected_at.desc())
            .limit(min(limit, 200))
        )
        if source:
            qy = qy.filter(Source.source_key == source)
        return {
            "items": [
                {
                    "source": k,
                    "change_type": e.change_type,
                    "detected_at": str(e.detected_at),
                    "from_artifact_id": str(e.from_artifact_id) if e.from_artifact_id else None,
                    "to_artifact_id": str(e.to_artifact_id) if e.to_artifact_id else None,
                    "detail": e.detail,
                }
                for e, k in qy.all()
            ]
        }


@mcp.tool()
def planning_versions(record_id: str) -> dict:
    """Version lineage for a planning record — original/amendment/
    replacement, effective dates, supersession links, metadata origins,
    and attached official documents."""
    from openquyhoach_core.db import session_scope
    from openquyhoach_core.models import PlanningRecord

    with session_scope() as s:
        rec = s.get(PlanningRecord, uuid.UUID(record_id))
        if rec is None:
            return {"error": "record not found"}
        return {
            "record": {"id": str(rec.id), "name": rec.name, "planning_type": rec.planning_type},
            "versions": [
                {
                    "id": str(v.id),
                    "version_number": v.version_number,
                    "status": v.status,
                    "effective_from": str(v.effective_from) if v.effective_from else None,
                    "effective_to": str(v.effective_to) if v.effective_to else None,
                    "decision_number": v.decision_number,
                    "approving_authority": v.approving_authority,
                    "metadata_origin": v.metadata_origin,
                    "supersedes_version_id": str(v.supersedes_version_id)
                    if v.supersedes_version_id
                    else None,
                    "documents": [
                        {
                            "id": str(d.id),
                            "document_number": d.document_number,
                            "title": d.title,
                            "metadata_origin": d.metadata_origin,
                            "artifact_id": str(d.artifact_id) if d.artifact_id else None,
                        }
                        for d in v.documents
                    ],
                }
                for v in rec.versions
            ],
        }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
