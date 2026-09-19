"""Browse endpoints: planning records, versions, datasets, admin units."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse, Response
from geoalchemy2.shape import to_shape
from openquyhoach_core.db import session_scope
from openquyhoach_core.models import (
    AdministrativeUnit,
    Dataset,
    Document,
    Feature,
    Layer,
    PlanningRecord,
    PlanningVersion,
    Publication,
    QualityObservation,
    SourceArtifact,
)
from openquyhoach_core.storage import artifact_store
from openquyhoach_core.text import vn_normalize
from sqlalchemy import func, select

from ..deps import PageDep
from ..serializers import (
    artifact_out,
    dataset_out,
    document_out,
    iso,
    layer_out,
    observation_out,
    record_out,
    unit_out,
    version_out,
)

router = APIRouter(prefix="/v1", tags=["browse"])


def _record_data_classes(s, record_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Classify each record by the source keys behind its artifacts.

    demo/* sources are synthetic fixtures; anything else observed real data.
    A record backed by both is honestly reported as "mixed"."""
    if not record_ids:
        return {}
    from openquyhoach_core.models import Source

    keys: dict[uuid.UUID, set[str]] = {r: set() for r in record_ids}
    ds_rows = (
        s.query(PlanningVersion.planning_record_id, Source.source_key)
        .join(Dataset, Dataset.planning_version_id == PlanningVersion.id)
        .join(SourceArtifact, Dataset.source_artifact_id == SourceArtifact.id)
        .join(Source, SourceArtifact.source_id == Source.id)
        .filter(PlanningVersion.planning_record_id.in_(record_ids))
        .all()
    )
    doc_rows = (
        s.query(PlanningVersion.planning_record_id, Source.source_key)
        .join(Document, Document.planning_version_id == PlanningVersion.id)
        .join(SourceArtifact, Document.artifact_id == SourceArtifact.id)
        .join(Source, SourceArtifact.source_id == Source.id)
        .filter(PlanningVersion.planning_record_id.in_(record_ids))
        .all()
    )
    for rid, key in ds_rows + doc_rows:
        keys.setdefault(rid, set()).add(key)
    out: dict[uuid.UUID, str] = {}
    for rid, ks in keys.items():
        if not ks:
            out[rid] = "unknown"
        elif all(k.startswith("demo/") for k in ks):
            out[rid] = "synthetic"
        elif any(k.startswith("demo/") for k in ks):
            out[rid] = "mixed"
        else:
            out[rid] = "official"
    return out


@router.get("/planning-records")
def list_records(
    page: PageDep,
    q: str | None = Query(None),
    jurisdiction: str | None = None,
):
    with session_scope() as s:
        qy = s.query(PlanningRecord)
        if q:
            qy = qy.filter(PlanningRecord.normalized_title.like(f"%{vn_normalize(q)}%"))
        if jurisdiction:
            qy = qy.filter(PlanningRecord.jurisdiction == jurisdiction)
        total = qy.count()
        rows = qy.order_by(PlanningRecord.title).offset(page.offset).limit(page.limit).all()
        classes = _record_data_classes(s, [r.id for r in rows])
        items = []
        for r in rows:
            out = record_out(r)
            out["data_class"] = classes.get(r.id, "unknown")
            items.append(out)
        return {"total": total, "items": items}


@router.get("/planning-records/{record_id}")
def get_record(record_id: uuid.UUID):
    with session_scope() as s:
        r = s.get(PlanningRecord, record_id)
        if r is None:
            raise HTTPException(404, "planning record not found")
        versions = (
            s.query(PlanningVersion)
            .filter_by(planning_record_id=r.id)
            .order_by(PlanningVersion.effective_from.nulls_last())
            .all()
        )
        out = record_out(r)
        out["data_class"] = _record_data_classes(s, [r.id]).get(r.id, "unknown")
        out["versions"] = [version_out(v) for v in versions]
        return out


@router.get("/planning-versions/{version_id}")
def get_version(version_id: uuid.UUID):
    with session_scope() as s:
        v = s.get(PlanningVersion, version_id)
        if v is None:
            raise HTTPException(404, "planning version not found")
        out = version_out(v)
        out["record"] = record_out(v.record)
        out["datasets"] = [
            dataset_out(d) for d in s.query(Dataset).filter_by(planning_version_id=v.id).all()
        ]
        out["documents"] = [
            document_out(d) for d in s.query(Document).filter_by(planning_version_id=v.id).all()
        ]
        out["publications"] = [
            {
                "id": str(p.id),
                "status": p.status,
                "published_at": iso(p.published_at),
                "checksum_sha256": p.checksum_sha256,
            }
            for p in s.query(Publication).filter_by(planning_version_id=v.id).all()
        ]
        return out


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: uuid.UUID):
    with session_scope() as s:
        d = s.get(Dataset, dataset_id)
        if d is None:
            raise HTTPException(404, "dataset not found")
        out = dataset_out(d)
        out["layers"] = [layer_out(ly) for ly in s.query(Layer).filter_by(dataset_id=d.id).all()]
        if d.source_artifact_id:
            a = s.get(SourceArtifact, d.source_artifact_id)
            out["source_artifact"] = artifact_out(a) if a else None
        out["quality_observations"] = [
            observation_out(o)
            for o in s.query(QualityObservation)
            .filter_by(target_type="dataset", target_id=d.id, resolved_at=None)
            .limit(200)
            .all()
        ]
        return out


@router.get("/datasets/{dataset_id}/features")
def dataset_features(
    dataset_id: uuid.UUID,
    page: PageDep,
    layer: str | None = Query(None, description="canonical layer name"),
    bbox: str | None = Query(None, description="minx,miny,maxx,maxy in EPSG:4326"),
):
    """Small GeoJSON pages only — full extents come from tiles, not this API."""
    bbox_vals = None
    if bbox:
        try:
            bbox_vals = [float(v) for v in bbox.split(",")]
            assert len(bbox_vals) == 4
        except (ValueError, AssertionError):
            raise HTTPException(400, "bbox must be minx,miny,maxx,maxy") from None
    with session_scope() as s:
        d = s.get(Dataset, dataset_id)
        if d is None:
            raise HTTPException(404, "dataset not found")
        layer_ids = [ly.id for ly in s.query(Layer).filter_by(dataset_id=d.id).all()]
        if layer:
            layer_ids = [
                ly.id
                for ly in s.query(Layer).filter_by(dataset_id=d.id, canonical_name=layer).all()
            ]
        qy = (
            s.query(Feature, Layer.canonical_name)
            .join(Layer, Feature.layer_id == Layer.id)
            .filter(Feature.layer_id.in_(layer_ids or [uuid.uuid4()]))
        )
        if bbox_vals:
            qy = qy.filter(
                func.ST_Intersects(
                    Feature.geometry,
                    func.ST_MakeEnvelope(*bbox_vals, 4326),
                )
            )
        total = qy.count()
        rows = qy.offset(page.offset).limit(min(page.limit, 200)).all()
        return {
            "total": total,
            "features": [
                {
                    "id": str(f.id),
                    "layer": lname,
                    "classification": f.classification,
                    "properties": f.properties,
                    "geometry": to_shape(f.geometry).__geo_interface__
                    if f.geometry is not None
                    else None,
                }
                for f, lname in rows
            ],
        }


@router.get("/documents")
def list_documents(
    page: PageDep,
    version_id: uuid.UUID | None = None,
    document_type: str | None = None,
):
    with session_scope() as s:
        qy = s.query(Document)
        if version_id:
            qy = qy.filter(Document.planning_version_id == version_id)
        if document_type:
            qy = qy.filter(Document.document_type == document_type)
        total = qy.count()
        rows = (
            qy.order_by(Document.signed_date.nulls_last(), Document.document_number)
            .offset(page.offset)
            .limit(page.limit)
            .all()
        )
        return {"total": total, "items": [document_out(d) for d in rows]}


@router.get("/documents/{doc_id}")
def get_document(doc_id: uuid.UUID):
    with session_scope() as s:
        d = s.get(Document, doc_id)
        if d is None:
            raise HTTPException(404, "document not found")
        out = document_out(d)
        if d.artifact_id:
            a = s.get(SourceArtifact, d.artifact_id)
            out["artifact"] = artifact_out(a) if a else None
        return out


@router.get("/documents/{doc_id}/download")
def download_document(doc_id: uuid.UUID):
    """Redirect to a presigned object URL, or stream bytes when the store
    is filesystem-backed (local dev/tests)."""
    with session_scope() as s:
        d = s.get(Document, doc_id)
        if d is None or d.artifact_id is None:
            raise HTTPException(404, "document not found")
        a = s.get(SourceArtifact, d.artifact_id)
        if a is None:
            raise HTTPException(404, "artifact missing")
        key, filename, mime = a.object_storage_key, a.filename, a.mime_type
    if key is None:
        raise HTTPException(404, "artifact not stored")

    store = artifact_store()
    url = store.presigned_url(key)
    if url.startswith(("http://", "https://")):
        return RedirectResponse(url, status_code=302)
    # filesystem store: stream the artifact directly
    try:
        data = store.get(key)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, "artifact object missing") from exc
    headers = {"Content-Disposition": f'attachment; filename="{filename or "document"}"'}
    return Response(
        data,
        media_type=mime or "application/octet-stream",
        headers=headers,
    )


@router.get("/admin-units")
def list_units(page: PageDep, level: str | None = None, q: str | None = None):
    with session_scope() as s:
        qy = s.query(AdministrativeUnit)
        if level:
            qy = qy.filter(AdministrativeUnit.level == level)
        if q:
            qy = qy.filter(AdministrativeUnit.normalized_name.like(f"%{vn_normalize(q)}%"))
        total = qy.count()
        rows = qy.order_by(AdministrativeUnit.name).offset(page.offset).limit(page.limit).all()
        return {"total": total, "items": [unit_out(u) for u in rows]}


@router.get("/admin-units/{unit_id}")
def get_unit(unit_id: uuid.UUID):
    with session_scope() as s:
        u = s.get(AdministrativeUnit, unit_id)
        if u is None:
            raise HTTPException(404, "admin unit not found")
        out = unit_out(u)
        if u.geometry is not None:
            out["bbox"] = s.scalar(select(func.ST_Extent(u.geometry)))
        out["coverage"] = None
        from openquyhoach_core.models import CoverageSummary

        cov = s.query(CoverageSummary).filter_by(admin_unit_id=u.id).one_or_none()
        if cov:
            out["coverage"] = {
                "state": cov.state,
                "source_count": cov.source_count,
                "document_count": cov.document_count,
                "dataset_count": cov.dataset_count,
                "reviewed_count": cov.reviewed_count,
                "last_checked": str(cov.last_checked) if cov.last_checked else None,
            }
        return out
