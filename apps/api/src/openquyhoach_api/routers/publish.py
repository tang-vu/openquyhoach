"""Publication, tiles and compare endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response
from openquyhoach_core.db import get_engine, session_scope
from openquyhoach_core.errors import UnreviewedDataError
from openquyhoach_core.models import ChangeSet, Publication
from openquyhoach_core.queue import get_queue
from openquyhoach_geo.mvt import fetch_mvt
from openquyhoach_services.compare import compute_changeset
from openquyhoach_services.publish import (
    check_publishable,
    publish_version,
    read_publication_tile,
)
from pydantic import BaseModel
from sqlalchemy import text

from ..deps import AdminGuard, PageDep
from ..serializers import publication_out

router = APIRouter(prefix="/v1", tags=["publish"])


# ------------------------------------------------------------------ tiles


@router.get("/tiles/{z}/{x}/{y}.pbf")
def live_tile(z: int, x: int, y: int):
    """Live MVT over published datasets. For snapshot tiles use the
    publication endpoints instead."""
    if not (0 <= z <= 22):
        raise HTTPException(400, "invalid zoom")
    blob = fetch_mvt(
        get_engine(),
        z,
        x,
        y,
        where="d.published",
        params={},
        layer_name="planning",
    )
    if not blob:
        raise HTTPException(404, "empty tile")
    return Response(blob, media_type="application/vnd.mapbox-vector-tile")


# ------------------------------------------------------------- publication


class PublishRequest(BaseModel):
    planning_version_id: uuid.UUID
    max_zoom: int = 14
    allow_unreviewed: bool = False
    async_: bool = False


@router.post("/publish", dependencies=[AdminGuard])
def publish(req: PublishRequest):
    gate = check_publishable(req.planning_version_id, allow_unreviewed=req.allow_unreviewed)
    if not gate["ok"]:
        raise HTTPException(409, detail=gate)
    if req.async_:
        job = get_queue().enqueue(
            "publish_version",
            planning_version_id=str(req.planning_version_id),
            max_zoom=req.max_zoom,
            allow_unreviewed=req.allow_unreviewed,
        )
        return {"job_id": job, "queued": True}
    try:
        pub_id = publish_version(
            req.planning_version_id,
            max_zoom=req.max_zoom,
            allow_unreviewed=req.allow_unreviewed,
            actor="api",
        )
    except UnreviewedDataError as exc:
        raise HTTPException(409, detail=exc.detail) from exc
    return {"publication_id": str(pub_id), "queued": False}


@router.get("/publications")
def list_publications(page: PageDep):
    with session_scope() as s:
        qy = s.query(Publication).order_by(Publication.published_at.desc())
        total = qy.count()
        rows = qy.offset(page.offset).limit(page.limit).all()
        return {"total": total, "items": [publication_out(p) for p in rows]}


@router.get("/publications/{pub_id}")
def get_publication(pub_id: uuid.UUID):
    with session_scope() as s:
        p = s.get(Publication, pub_id)
        if p is None:
            raise HTTPException(404, "publication not found")
        out = publication_out(p)
        out["manifest"] = p.manifest
        return out


@router.get("/publications/{pub_id}/manifest.json")
def get_manifest(pub_id: uuid.UUID):
    with session_scope() as s:
        p = s.get(Publication, pub_id)
        if p is None:
            raise HTTPException(404, "publication not found")
        return p.manifest


@router.get("/publications/{pub_id}/tiles/{z}/{x}/{y}.pbf")
def publication_tile(pub_id: uuid.UUID, z: int, x: int, y: int):
    tile = read_publication_tile(pub_id, z, x, y)
    if tile is None:
        raise HTTPException(404, "tile not found in archive")
    return Response(tile, media_type="application/vnd.mapbox-vector-tile")


# ---------------------------------------------------------------- compare


@router.get("/compare")
def compare_layers(from_layer: uuid.UUID, to_layer: uuid.UUID):
    cs_id = compute_changeset(from_layer, to_layer)
    with session_scope() as s:
        cs = s.get(ChangeSet, cs_id)
        if cs is None:
            raise HTTPException(404, "changeset not found")
        return changeset_out(cs)


@router.get("/changesets/{cs_id}")
def get_changeset(cs_id: uuid.UUID):
    with session_scope() as s:
        cs = s.get(ChangeSet, cs_id)
        if cs is None:
            raise HTTPException(404, "changeset not found")
        return changeset_out(cs)


def changeset_out(cs: ChangeSet) -> dict:
    return {
        "id": str(cs.id),
        "from_layer_id": str(cs.from_layer_id),
        "to_layer_id": str(cs.to_layer_id),
        "algorithm": cs.algorithm,
        "summary": cs.summary,
        "entries": [
            {
                "change_type": e.change_type,
                "match_key": e.match_key,
                "from_feature_id": str(e.from_feature_id) if e.from_feature_id else None,
                "to_feature_id": str(e.to_feature_id) if e.to_feature_id else None,
                "delta_area_m2": e.delta_area_m2,
                "detail": e.detail,
            }
            for e in cs.entries
        ],
    }


@router.get("/rasters/{dataset_id}/tiles/{z}/{x}/{y}.png")
def raster_tile(dataset_id: uuid.UUID, z: int, x: int, y: int):
    """XYZ tile rendered from a published raster dataset's stored COG."""
    import io

    from openquyhoach_core.models import Dataset, SourceArtifact
    from openquyhoach_core.storage import artifact_store

    with session_scope() as s:
        d = s.get(Dataset, dataset_id)
        if d is None or d.dataset_type != "raster":
            raise HTTPException(404, "raster dataset not found")
        if not d.published:
            raise HTTPException(403, "dataset not published")
        a = s.get(SourceArtifact, d.source_artifact_id) if d.source_artifact_id else None
        if a is None:
            raise HTTPException(404, "no source artifact")
        key = a.object_storage_key
    data = artifact_store().get(key)
    try:
        import rasterio
        from rio_tiler.errors import TileOutsideBounds
        from rio_tiler.io import Reader

        with rasterio.open(io.BytesIO(data)) as src, Reader(input=None, dataset=src) as cog:
            img = cog.tile(x, y, z)
            png = img.render(img_format="PNG")
        return Response(png, media_type="image/png")
    except TileOutsideBounds:
        # requested XYZ tile doesn't intersect the raster — a normal map event
        raise HTTPException(404, "tile outside raster extent") from None
    except Exception as exc:
        raise HTTPException(422, f"tile render failed: {exc}") from exc


# --------------------------------------------------------------- versions


@router.get("/versions/{version_id}/extent")
def version_extent(version_id: uuid.UUID):
    """BBox + zoom hint for the map to frame a planning version."""
    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT ST_Extent(ST_Transform(f.geometry, 4326))::text
                FROM features f
                JOIN layers l ON l.id = f.layer_id
                JOIN datasets d ON d.id = l.dataset_id
                WHERE d.planning_version_id = :vid
                """
            ),
            {"vid": version_id},
        ).fetchone()
    if not row or not row[0]:
        raise HTTPException(404, "no geometry for version")
    nums = row[0].replace("BOX(", "").replace(")", "").replace(",", " ").split()
    return {"bbox": [float(n) for n in nums]}
