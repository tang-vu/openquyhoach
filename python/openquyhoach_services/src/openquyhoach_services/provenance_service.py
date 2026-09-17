"""Provenance graph assembly — walk lineage from any entity backwards."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from openquyhoach_core.db import session_scope
from openquyhoach_core.models import (
    Dataset,
    Document,
    Feature,
    GeoreferenceJob,
    Layer,
    PlanningVersion,
    ProvenanceEvent,
    Publication,
    Source,
    SourceArtifact,
)


@dataclass
class Node:
    entity_type: str
    entity_id: str
    label: str
    meta: dict = field(default_factory=dict)


@dataclass
class Edge:
    src: str  # "type:id"
    dst: str
    operation: str
    at: str | None = None


def _label(session, entity_type: str, entity_id) -> tuple[str, dict]:
    table = {
        "artifact": SourceArtifact,
        "document": Document,
        "dataset": Dataset,
        "layer": Layer,
        "feature": Feature,
        "georef_job": GeoreferenceJob,
        "publication": Publication,
        "planning_version": PlanningVersion,
        "source": Source,
    }.get(entity_type)
    if table is None:
        return entity_type, {}
    obj = session.get(table, uuid.UUID(str(entity_id)))
    if obj is None:
        return f"{entity_type} (deleted)", {}
    for attr in ("filename", "canonical_name", "title", "name", "source_key"):
        v = getattr(obj, attr, None)
        if v:
            return str(v), {}
    return str(entity_id), {}


def provenance_graph(entity_type: str, entity_id: str | uuid.UUID, *, max_depth: int = 50) -> dict:
    """BFS over provenance_events following input_refs.

    Returns {nodes, edges} — the UI renders it as a DAG.
    """
    with session_scope() as s:
        nodes: dict[str, Node] = {}
        edges: list[Edge] = []
        queue = [(entity_type, str(entity_id), 0)]
        seen = set()
        while queue:
            et, eid, depth = queue.pop(0)
            key = f"{et}:{eid}"
            if key in seen or depth > max_depth:
                continue
            seen.add(key)
            label, meta = _label(s, et, eid)
            nodes[key] = Node(et, eid, label, meta)
            events = (
                s.query(ProvenanceEvent)
                .filter(
                    ProvenanceEvent.entity_type == et,
                    ProvenanceEvent.entity_id == uuid.UUID(eid),
                )
                .order_by(ProvenanceEvent.created_at)
                .all()
            )
            for ev in events:
                for ref in ev.input_refs or []:
                    rt, rid = ref.get("entity_type"), ref.get("entity_id")
                    if not rid:
                        # bare URL input — model as source node
                        rid = ref.get("url")
                        rt = "url"
                    if not rid:
                        continue
                    rkey = f"{rt}:{rid}"
                    if rkey not in nodes:
                        nodes[rkey] = Node(
                            rt, str(rid), str(rid)[:120], {"sha256": ref.get("sha256")}
                        )
                    edges.append(
                        Edge(
                            rkey,
                            key,
                            str(ev.operation),
                            ev.created_at.isoformat() if ev.created_at else None,
                        )
                    )
                    if rt != "url":
                        queue.append((rt, str(rid), depth + 1))
        return {
            "nodes": [vars(n) for n in nodes.values()],
            "edges": [vars(e) for e in edges],
        }


def provenance_summary_for_feature(feature_id: uuid.UUID) -> dict:
    """Compact provenance summary embedded in every point-query hit."""
    with session_scope() as s:
        f = s.get(Feature, feature_id)
        if f is None:
            return {}
        layer = s.get(Layer, f.layer_id)
        ds = s.get(Dataset, layer.dataset_id) if layer else None
        version = s.get(PlanningVersion, ds.planning_version_id) if ds else None
        artifact = (
            s.get(SourceArtifact, ds.source_artifact_id) if ds and ds.source_artifact_id else None
        )
        source = s.get(Source, artifact.source_id) if artifact and artifact.source_id else None
        return {
            "dataset": {"id": str(ds.id), "name": ds.name} if ds else None,
            "layer": {"id": str(layer.id), "name": layer.canonical_name} if layer else None,
            "derivation_level": ds.derivation_level if ds else None,
            "review_status": ds.review_status if ds else None,
            "planning_version": {
                "id": str(version.id),
                "label": version.version_label,
                "approval_decision_number": version.approval_decision_number,
                "approval_date": str(version.approval_date) if version.approval_date else None,
                "effective_from": str(version.effective_from) if version.effective_from else None,
                "legal_status": version.legal_status,
            }
            if version
            else None,
            "artifact": {
                "id": str(artifact.id),
                "sha256": artifact.content_sha256,
                "filename": artifact.filename,
                "retrieved_at": artifact.retrieval_time.isoformat()
                if artifact.retrieval_time
                else None,
                "canonical_url": artifact.canonical_url,
            }
            if artifact
            else None,
            "source": {
                "key": source.source_key,
                "name": source.name,
                "base_url": source.base_url,
            }
            if source
            else None,
        }
