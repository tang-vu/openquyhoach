"""Row → dict serializers. Kept explicit — API shape is a contract."""

from __future__ import annotations

from openquyhoach_core.models import (
    AdministrativeUnit,
    Dataset,
    Document,
    IngestionRun,
    Layer,
    PlanningRecord,
    PlanningVersion,
    Publication,
    QualityObservation,
    ReviewTask,
    Source,
    SourceArtifact,
)


def iso(v):
    return v.isoformat() if v else None


def source_out(s: Source) -> dict:
    return {
        "id": str(s.id),
        "key": s.source_key,
        # demo/* descriptors are deterministic synthetic fixtures — every
        # other source key denotes an observed official/derived real source
        "data_class": "synthetic" if s.source_key.startswith("demo/") else "official",
        "name": s.name,
        "source_type": s.source_type,
        "base_url": s.base_url,
        "jurisdiction": s.jurisdiction,
        "terms_url": s.terms_url,
        "license": s.license,
        "rights_statement": s.rights_statement,
        "redistribution_status": s.redistribution_status,
        "enabled": s.enabled,
        "priority": s.priority,
        "authority_id": str(s.authority_id) if s.authority_id else None,
        "admin_unit_id": str(s.admin_unit_id) if s.admin_unit_id else None,
    }


def run_out(r: IngestionRun) -> dict:
    return {
        "id": str(r.id),
        "source_id": str(r.source_id) if r.source_id else None,
        "status": r.status,
        "trigger": r.trigger,
        "started_at": iso(r.started_at),
        "completed_at": iso(r.completed_at),
        "discovered": r.discovered_count,
        "downloaded": r.downloaded_count,
        "imported": r.imported_count,
        "rejected": r.rejected_count,
        "warnings": r.warning_count,
        "error": r.error_summary,
    }


def record_out(r: PlanningRecord) -> dict:
    return {
        "id": str(r.id),
        "title": r.title,
        "normalized_title": r.normalized_title,
        "planning_type": r.planning_type,
        "scale": r.scale,
        "jurisdiction": r.jurisdiction,
        "official_information_code": r.official_information_code,
        "approving_authority": r.approving_authority,
        "admin_unit_id": str(r.admin_unit_id) if r.admin_unit_id else None,
        "status": r.status,
    }


def version_out(v: PlanningVersion) -> dict:
    return {
        "id": str(v.id),
        "planning_record_id": str(v.planning_record_id),
        "version_kind": v.version_kind,
        "version_label": v.version_label,
        "approval_decision_number": v.approval_decision_number,
        "approval_date": str(v.approval_date) if v.approval_date else None,
        "effective_from": str(v.effective_from) if v.effective_from else None,
        "effective_to": str(v.effective_to) if v.effective_to else None,
        "legal_status": v.legal_status,
        "metadata_origin": v.metadata_origin,
        "supersedes_version_id": str(v.supersedes_version_id) if v.supersedes_version_id else None,
    }


def dataset_out(d: Dataset) -> dict:
    return {
        "id": str(d.id),
        "name": d.name,
        "dataset_group": d.dataset_group,
        "dataset_type": d.dataset_type,
        "planning_version_id": str(d.planning_version_id),
        "derivation_level": d.derivation_level,
        "review_status": d.review_status,
        "quality_state": d.quality_state,
        "published": d.published,
        "original_format": d.original_format,
        "original_crs": d.original_crs,
        "source_artifact_id": str(d.source_artifact_id) if d.source_artifact_id else None,
    }


def layer_out(ly: Layer) -> dict:
    return {
        "id": str(ly.id),
        "canonical_name": ly.canonical_name,
        "source_name": ly.source_name,
        "title": ly.title,
        "thematic_group": ly.thematic_group,
        "geometry_type": ly.geometry_type,
        "feature_count": ly.feature_count,
    }


def document_out(d: Document) -> dict:
    return {
        "id": str(d.id),
        "document_type": d.document_type,
        "document_number": d.document_number,
        "title": d.title,
        "signed_date": str(d.signed_date) if d.signed_date else None,
        "issuing_authority": d.issuing_authority,
        "metadata_origin": d.metadata_origin,
        "field_origins": (d.meta or {}).get("field_origins"),
        "page_count": d.page_count,
        "artifact_id": str(d.artifact_id) if d.artifact_id else None,
        "planning_version_id": str(d.planning_version_id),
        "candidate_codes": (d.meta or {}).get("candidate_codes"),
    }


def artifact_out(a: SourceArtifact) -> dict:
    return {
        "id": str(a.id),
        "filename": a.filename,
        "sha256": a.content_sha256,
        "canonical_url": a.canonical_url,
        "mime_type": a.mime_type,
        "file_size": a.file_size,
        "detected_format": a.detected_format,
        "status": a.status,
        "retrieved_at": iso(a.retrieval_time),
        "source_id": str(a.source_id) if a.source_id else None,
    }


def publication_out(p: Publication) -> dict:
    return {
        "id": str(p.id),
        "planning_version_id": str(p.planning_version_id),
        "status": p.status,
        "checksum_sha256": p.checksum_sha256,
        "artifact_key": p.artifact_key,
        "manifest_key": p.manifest_key,
        "feature_count": p.feature_count,
        "bbox": p.bbox,
        "min_zoom": p.min_zoom,
        "max_zoom": p.max_zoom,
        "published_at": iso(p.published_at),
    }


def observation_out(o: QualityObservation) -> dict:
    return {
        "id": str(o.id),
        "rule_code": o.rule_code,
        "severity": o.severity,
        "target_type": o.target_type,
        "target_id": str(o.target_id),
        "message": o.message,
        "evidence": o.evidence,
        "resolved_at": iso(o.resolved_at),
    }


def task_out(t: ReviewTask) -> dict:
    return {
        "id": str(t.id),
        "target_type": t.target_type,
        "target_id": str(t.target_id),
        "task_type": t.task_type,
        "priority": t.priority,
        "status": t.status,
        "reason": t.reason,
        "evidence": t.evidence,
        "created_at": iso(t.created_at),
    }


def unit_out(u: AdministrativeUnit) -> dict:
    return {
        "id": str(u.id),
        "name": u.name,
        "level": u.level,
        "official_code": u.official_code,
        "valid_from": str(u.valid_from) if u.valid_from else None,
        "valid_to": str(u.valid_to) if u.valid_to else None,
        "parent_id": str(u.parent_id) if u.parent_id else None,
    }
