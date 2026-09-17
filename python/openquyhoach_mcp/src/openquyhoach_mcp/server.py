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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
