"""Publication: validated data → immutable PMTiles snapshot + manifest.

Pipeline per spec §27:

    planning version → validated canonical features → tile set (ST_AsMVT)
      → PMTiles (deterministic bytes) → sha256 → object storage → manifest
      → Publication row → provenance event

A snapshot is reproducible: identical DB content produces identical bytes
(PMTiles writer is deterministic; gzip is written with mtime=0).
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime

import mercantile
from openquyhoach_core.db import get_engine, session_scope
from openquyhoach_core.enums import (
    DerivationLevel,
    ProvenanceOp,
    PublicationStatus,
    ReviewStatus,
)
from openquyhoach_core.errors import UnreviewedDataError
from openquyhoach_core.hashing import sha256_bytes
from openquyhoach_core.logging import get_logger
from openquyhoach_core.manifest import (
    DataManifest,
    ManifestDataset,
    ManifestQuality,
    ManifestSource,
)
from openquyhoach_core.models import (
    Authority,
    Dataset,
    Layer,
    PlanningVersion,
    Publication,
    QualityObservation,
    Source,
    SourceArtifact,
)
from openquyhoach_core.provenance import record_event
from openquyhoach_core.storage import published_store
from openquyhoach_geo.mvt import fetch_mvt
from openquyhoach_geo.pmtiles import Tile, write_pmtiles
from sqlalchemy import text

log = get_logger(__name__)

OFFICIAL_LEVELS = {
    DerivationLevel.OFFICIAL_VECTOR.value,
    DerivationLevel.OFFICIAL_RASTER.value,
    DerivationLevel.OFFICIAL_DOCUMENT.value,
}

DEFAULT_MAX_ZOOM = 14


def _version_bbox(version_id: uuid.UUID) -> list[float] | None:
    sql = text(
        """
        SELECT ST_Extent(ST_Transform(f.geometry, 4326))::text
        FROM features f
        JOIN layers ly ON ly.id = f.layer_id
        JOIN datasets d ON d.id = ly.dataset_id
        WHERE d.planning_version_id = :vid
        """
    )
    with get_engine().connect() as conn:
        row = conn.execute(sql, {"vid": version_id}).fetchone()
    if not row or not row[0]:
        return None
    # "BOX(minx miny,maxx maxy)"
    nums = row[0].replace("BOX(", "").replace(")", "").replace(",", " ").split()
    return [float(n) for n in nums]


def _collect_datasets(version_id: uuid.UUID) -> list[Dataset]:
    """All datasets of a version — review gate + publish flag apply to every
    dataset type (vector, raster, document). Only MVT tile *rendering* is
    vector-specific; rasters have no layers so they contribute no tiles."""
    with session_scope() as s:
        return s.query(Dataset).filter(Dataset.planning_version_id == version_id).all()


def check_publishable(version_id: uuid.UUID, *, allow_unreviewed: bool = False) -> dict:
    """Publication gate — every dataset must be reviewed or official-level."""
    datasets = _collect_datasets(version_id)
    blocked = []
    for d in datasets:
        official = d.derivation_level in OFFICIAL_LEVELS
        reviewed = d.review_status == ReviewStatus.APPROVED.value
        if not official and not reviewed and not allow_unreviewed:
            blocked.append(
                {
                    "dataset_id": str(d.id),
                    "name": d.name,
                    "derivation_level": d.derivation_level,
                    "review_status": d.review_status,
                }
            )
    return {"ok": not blocked, "blocked": blocked, "dataset_count": len(datasets)}


def build_tiles(
    version_id: uuid.UUID, *, max_zoom: int = DEFAULT_MAX_ZOOM, min_zoom: int = 0
) -> tuple[list[Tile], list[float] | None]:
    bbox = _version_bbox(version_id)
    if bbox is None:
        return [], None
    engine = get_engine()
    # `published` flips only after this snapshot is stored — gating on it
    # here would produce empty archives. The review gate runs beforehand.
    where = "d.planning_version_id = :pvid"
    tiles: list[Tile] = []
    for z in range(min_zoom, max_zoom + 1):
        for t in mercantile.tiles(*bbox, zooms=[z]):
            blob = fetch_mvt(
                engine,
                z,
                t.x,
                t.y,
                where=where,
                params={"pvid": version_id},
                layer_name="planning",
            )
            if blob:
                tiles.append(Tile(z, t.x, t.y, blob))
    return tiles, bbox


def build_manifest(
    version_id: uuid.UUID, *, pmtiles_sha: str | None, bbox: list[float] | None
) -> DataManifest:
    with session_scope() as s:
        version = s.get(PlanningVersion, version_id)
        assert version is not None
        record = version.record
        datasets = s.query(Dataset).filter(Dataset.planning_version_id == version_id).all()
        artifact_ids = {d.source_artifact_id for d in datasets if d.source_artifact_id}
        if version.source_artifact_id:
            artifact_ids.add(version.source_artifact_id)
        artifacts = {
            a.id: a
            for a in s.query(SourceArtifact)
            .filter(SourceArtifact.id.in_([a for a in artifact_ids if a]))
            .all()
        }
        src_rows = {}
        for a in artifacts.values():
            if a.source_id:
                src = s.get(Source, a.source_id)
                if src:
                    src_rows[a.id] = src
        levels = [d.derivation_level for d in datasets]
        # least-authoritative level = the last one in enum order present
        rank = {lv.value: i for i, lv in enumerate(DerivationLevel)}
        worst = (
            max(levels, key=lambda lv: rank.get(lv, -1))
            if levels
            else DerivationLevel.REFERENCE_APPROXIMATE.value
        )

        obs = (
            s.query(QualityObservation)
            .filter(
                QualityObservation.target_type == "dataset",
                QualityObservation.target_id.in_([d.id for d in datasets] or [uuid.uuid4()]),
                QualityObservation.resolved_at.is_(None),
            )
            .all()
        )
        by_sev: dict[str, int] = {}
        for o in obs:
            by_sev[o.severity] = by_sev.get(o.severity, 0) + 1

        sources: list[ManifestSource] = []
        for a in artifacts.values():
            src = src_rows.get(a.id)
            auth = s.get(Authority, src.authority_id) if src and src.authority_id else None
            sources.append(
                ManifestSource(
                    authority=auth.canonical_name if auth else (src.name if src else None),
                    source_key=src.source_key if src else None,
                    canonical_url=a.canonical_url,
                    artifact_sha256=a.content_sha256,
                    retrieved_at=a.retrieval_time,
                    rights_statement=src.rights_statement if src else None,
                    license=src.license if src else None,
                )
            )

        return DataManifest(
            planning_record=str(record.id),
            planning_record_title=record.title,
            planning_version=str(version.id),
            version_label=version.version_label,
            authority=version.record.approving_authority,
            legal_status=version.legal_status,
            approval_decision_number=version.approval_decision_number,
            approval_date=str(version.approval_date) if version.approval_date else None,
            effective_from=str(version.effective_from) if version.effective_from else None,
            effective_to=str(version.effective_to) if version.effective_to else None,
            sources=sources,
            datasets=[
                ManifestDataset(
                    dataset_id=str(d.id),
                    name=d.name,
                    dataset_group=d.dataset_group,
                    dataset_type=d.dataset_type,
                    derivation_level=d.derivation_level,
                    review_status=d.review_status,
                    layer_count=len(d.layers),
                    feature_count=sum(ly.feature_count for ly in d.layers),
                )
                for d in datasets
            ],
            derivation_level=worst,
            quality=ManifestQuality(
                open_observations=len(obs),
                by_severity=by_sev,
                rule_codes=sorted({o.rule_code for o in obs}),
            ),
            artifacts=[
                {
                    "sha256": a.content_sha256,
                    "filename": a.filename,
                    "detected_format": a.detected_format,
                    "size": a.file_size,
                }
                for a in artifacts.values()
            ],
            bbox=bbox,
            pmtiles_sha256=pmtiles_sha,
            published_at=datetime.now(UTC),
            software_commit=None,
        )


def publish_version(
    version_id: uuid.UUID,
    *,
    max_zoom: int = DEFAULT_MAX_ZOOM,
    allow_unreviewed: bool = False,
    actor: str = "cli",
) -> uuid.UUID:
    """Build + store an immutable publication. Returns publication id."""
    gate = check_publishable(version_id, allow_unreviewed=allow_unreviewed)
    if not gate["ok"]:
        raise UnreviewedDataError(
            "publication blocked: datasets pending review",
            detail=gate,
        )

    tiles, bbox = build_tiles(version_id, max_zoom=max_zoom)
    manifest = build_manifest(version_id, pmtiles_sha=None, bbox=bbox)

    meta_json = manifest.model_dump(mode="json")
    meta_json["vector_layers"] = _vector_layers_meta(version_id)

    buf = io.BytesIO()
    stats = write_pmtiles(
        tiles,
        metadata=meta_json,
        out=buf,
        min_lon=bbox[0] if bbox else -180,
        min_lat=bbox[1] if bbox else -85,
        max_lon=bbox[2] if bbox else 180,
        max_lat=bbox[3] if bbox else 85,
        center_lon=(bbox[0] + bbox[2]) / 2 if bbox else 0,
        center_lat=(bbox[1] + bbox[3]) / 2 if bbox else 0,
        center_zoom=min(8, max_zoom),
    )
    payload = buf.getvalue()
    sha = sha256_bytes(payload)
    key = f"publications/{version_id}/{sha[:12]}/planning.pmtiles"
    manifest_key = f"publications/{version_id}/{sha[:12]}/manifest.json"

    store = published_store()
    store.put(key, payload, content_type="application/x-pmtiles")
    manifest.pmtiles_sha256 = sha
    store.put(
        manifest_key,
        manifest.model_dump_json(indent=2).encode(),
        content_type="application/json",
    )

    with session_scope() as s:
        pub = Publication(
            planning_version_id=version_id,
            status=PublicationStatus.PUBLISHED.value,
            artifact_key=key,
            manifest_key=manifest_key,
            manifest=manifest.model_dump(mode="json"),
            checksum_sha256=sha,
            feature_count=stats["num_tiles"],
            bbox=bbox,
            min_zoom=stats["min_zoom"],
            max_zoom=stats["max_zoom"],
            published_at=datetime.now(UTC),
        )
        s.add(pub)
        s.flush()
        # datasets become publicly visible
        for d in _collect_datasets(version_id):
            d.published = True
            s.merge(d)
        record_event(
            s,
            entity_type="publication",
            entity_id=pub.id,
            operation=ProvenanceOp.PUBLISHED,
            input_refs=[{"entity_type": "planning_version", "entity_id": str(version_id)}],
            tool="openquyhoach-services",
            tool_version="0.1.0",
            output_hash=sha,
            actor=actor,
            parameters={"tiles": stats["num_tiles"], "max_zoom": max_zoom},
        )
        log.info("publish.done", version=str(version_id), sha=sha[:16], tiles=stats["num_tiles"])
        return pub.id


def _vector_layers_meta(version_id: uuid.UUID) -> list[dict]:
    with session_scope() as s:
        layers = (
            s.query(Layer)
            .join(Dataset, Dataset.id == Layer.dataset_id)
            .filter(Dataset.planning_version_id == version_id)
            .all()
        )
        return [
            {
                "id": ly.canonical_name,
                "description": ly.title or ly.canonical_name,
                "fields": {
                    "classification": "String",
                    "name": "String",
                    "derivation_level": "String",
                },
            }
            for ly in layers
        ]


def read_publication_tile(pub_id: uuid.UUID, z: int, x: int, y: int) -> bytes | None:
    """Serve a tile out of a published PMTiles archive via range reads."""
    from openquyhoach_geo.pmtiles import PMTilesReader

    with session_scope() as s:
        pub = s.get(Publication, pub_id)
        if pub is None or not pub.artifact_key:
            return None
        data = published_store().get(pub.artifact_key)  # small archives: read once
    reader = PMTilesReader(data)
    return reader.get_tile(z, x, y)
