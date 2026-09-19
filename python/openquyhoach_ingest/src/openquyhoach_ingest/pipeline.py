"""Staged ingestion pipeline.

    DISCOVER → FETCH → CONTENT-ADDRESS → DETECT → METADATA → CRS → VALIDATE
             → NORMALIZE → PROVENANCE → REVIEW-GATE → PUBLISH

Properties:

* idempotent — artifacts dedupe on sha256; a dataset already imported from an
  artifact is not re-imported; re-runs are cheap.
* resumable — a failed run can be retried; completed stages are skipped.
* auditable — every stage emits provenance events with input/output hashes.
* format-dispatched — vector/raster/pdf/zip handlers are separate functions.

Publishing is a *separate* explicit step (openquyhoach publish) gated by
review state — ingestion alone never makes data authoritative.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from openquyhoach_core.db import session_scope
from openquyhoach_core.enums import (
    ArtifactStatus,
    DerivationLevel,
    IngestionStatus,
    MetadataOrigin,
    ProvenanceOp,
    ReviewStatus,
    TaskType,
)
from openquyhoach_core.errors import UnsupportedFormatError
from openquyhoach_core.hashing import sha256_file
from openquyhoach_core.logging import get_logger
from openquyhoach_core.models import (
    Dataset,
    Document,
    Feature,
    IngestionRun,
    Layer,
    PlanningRecord,
    PlanningVersion,
    ReviewTask,
    Source,
    SourceArtifact,
)
from openquyhoach_core.provenance import record_event
from openquyhoach_core.security import safe_extract_zip, sniff_format
from openquyhoach_core.storage import artifact_key, artifact_store
from openquyhoach_core.text import vn_normalize
from openquyhoach_geo.crs import CRSInfo, describe_crs
from openquyhoach_geo.vector import is_dwg, is_vector_file
from openquyhoach_geo.vn_gis import normalize_group_name
from openquyhoach_quality.engine import FeaturePayload, LayerPayload, ValidationContext, run_rules
from openquyhoach_quality.persist import persist_findings
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .connectors.base import FetchResult, SourceConfig
from .pdfmeta import inspect_pdf
from .sources import load_config

log = get_logger(__name__)

VECTOR_FORMATS = {"gpkg", "geojson", "shp", "kml", "dxf", "fgb", "sqlite", "gml", "json"}
RASTER_FORMATS = {"tiff", "png", "jpeg"}
DOC_FORMATS = {"pdf"}

TOOL = "openquyhoach-ingest"


def _git_commit() -> str | None:
    return os.environ.get("GIT_COMMIT") or os.environ.get("OQH_COMMIT")


# ---------------------------------------------------------------------------
# Planning record / version resolution
# ---------------------------------------------------------------------------


def _basename(url: str) -> str | None:
    """Filename from a file:// or https:// URL, ignoring query strings."""
    from urllib.parse import unquote, urlparse

    name = Path(unquote(urlparse(url).path)).name
    return name or None


def _parse_date(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    try:
        return date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        return None


def resolve_planning_version(
    session: Session,
    source_cfg: SourceConfig | None,
    artifact: SourceArtifact,
    hints: dict | None = None,
) -> PlanningVersion:
    """Get-or-create the planning record+version this artifact belongs to.

    Resolution order, strongest evidence first:

    1. the descriptor's ``planning:`` block — OFFICIAL_EXPLICIT
       (the descriptor author copied values from the official source);
    2. ``hints`` — machine-extracted candidates (PDF text, portal fields)
       — DERIVED_MACHINE, always review-gated;
    3. source name fallback — UNKNOWN placeholder for curation.

    ``hints`` keys mirror the planning block (title, decision_number,
    approval_date, effective_from, planning_type, scale,
    approving_authority, information_code, supersedes_decision).
    """
    planning = (source_cfg.meta.get("planning") if source_cfg else None) or {}
    hints = hints or {}
    derived = bool(hints) and not planning
    title = (
        planning.get("title")
        or hints.get("title")
        or (source_cfg.name if source_cfg else "Unattributed ingest")
    )
    info_code = planning.get("information_code") or hints.get("information_code")
    record = (
        session.query(PlanningRecord).filter_by(normalized_title=vn_normalize(title)).one_or_none()
    )
    if record is None and info_code:
        record = (
            session.query(PlanningRecord)
            .filter_by(official_information_code=info_code)
            .one_or_none()
        )
    if record is None:
        record = PlanningRecord(
            title=title,
            normalized_title=vn_normalize(title),
            planning_type=planning.get("planning_type") or hints.get("planning_type"),
            scale=planning.get("scale") or hints.get("scale"),
            jurisdiction=source_cfg.jurisdiction if source_cfg else None,
            approving_authority=planning.get("approving_authority")
            or hints.get("approving_authority")
            or (source_cfg.authority if source_cfg else None),
            official_information_code=info_code,
            status="active",
        )
        session.add(record)
        session.flush()

    decision = planning.get("decision_number") or hints.get("decision_number")
    version = None
    if decision:
        version = (
            session.query(PlanningVersion)
            .filter_by(planning_record_id=record.id, approval_decision_number=decision)
            .one_or_none()
        )
    hint_origin = hints.get("_origin") or MetadataOrigin.DERIVED_MACHINE.value
    origin = (
        MetadataOrigin.OFFICIAL_EXPLICIT.value
        if planning.get("decision_number")
        else (hint_origin if decision else MetadataOrigin.UNKNOWN.value)
    )
    if version is None:
        version = PlanningVersion(
            planning_record_id=record.id,
            version_kind=planning.get("version_kind") or "original",
            version_label=planning.get("version_label"),
            approval_decision_number=decision,
            approval_date=_parse_date(planning.get("approval_date") or hints.get("approval_date")),
            effective_from=_parse_date(
                planning.get("effective_from") or hints.get("effective_from")
            ),
            legal_status="approved" if decision else "unknown",
            metadata_origin=origin,
            source_artifact_id=artifact.id,
            notes="auto-created by ingestion" if not planning.get("decision_number") else None,
        )
        session.add(version)
        session.flush()
    elif version.metadata_origin in (None, MetadataOrigin.UNKNOWN.value) and origin != MetadataOrigin.UNKNOWN.value:
        # enrich an unexplained version — never downgrade a known origin
        version.metadata_origin = origin

    # supersedes lineage: a referenced earlier decision links versions
    supersedes = planning.get("supersedes_decision") or hints.get("supersedes_decision")
    if supersedes and version.supersedes_version_id is None:
        prior = (
            session.query(PlanningVersion)
            .filter(
                PlanningVersion.planning_record_id == record.id,
                PlanningVersion.approval_decision_number == supersedes,
                PlanningVersion.id != version.id,
            )
            .one_or_none()
        )
        if prior is not None:
            version.supersedes_version_id = prior.id
            if version.version_kind == "original":
                version.version_kind = "replacement"
    if derived:
        version.meta = {
            **(version.meta or {}),
            "metadata_hints": {
                k: v
                for k, v in hints.items()
                if v is not None and not k.startswith("_")
            },
        }
    return version


# ---------------------------------------------------------------------------
# Format handlers
# ---------------------------------------------------------------------------


def _transform_geom(geom, crs: CRSInfo):
    """source geom → canonical EPSG:4326. Returns (geom4326, transformed_bool)."""
    from openquyhoach_geo.crs import CANONICAL_SRID, canonical_transformer

    if not crs.identified or crs.epsg == CANONICAL_SRID:
        return geom, False
    transformer = canonical_transformer(crs)
    return shapely_transform(geom, transformer), True


def shapely_transform(geom, transformer):
    import shapely.ops

    return shapely.ops.transform(transformer.transform, geom)


def _ingest_vector(
    session: Session,
    artifact: SourceArtifact,
    path: Path,
    version: PlanningVersion,
    source_cfg: SourceConfig | None,
    run: IngestionRun,
) -> list[Dataset]:
    from openquyhoach_geo.geom import ewkb, to_postgis
    from openquyhoach_geo.vector import iter_features, list_layers

    parser = source_cfg.parser if source_cfg else {}
    layer_map = parser.get("layer_map") or {}
    aliases = parser.get("layer_map_aliases") or {}
    crs_override = parser.get("crs_override")
    default_level = (
        parser.get("default_derivation_level") or DerivationLevel.DERIVED_MACHINE_UNREVIEWED.value
    )
    datasets: list[Dataset] = []
    layers_info = list_layers(path)

    for linfo in layers_info:
        crs = describe_crs(crs_override) if crs_override else linfo.crs
        # match order: exact layer name, its alias, filename stem, stem's
        # alias — connectors name files after the remote layer so stems
        # carry meaning
        lcfg = {}
        for cand in (linfo.name, aliases.get(linfo.name), path.stem, aliases.get(path.stem)):
            if cand and cand in layer_map:
                lcfg = layer_map[cand]
                break
        group = normalize_group_name(lcfg.get("thematic_group") or linfo.name)
        ds = Dataset(
            planning_version_id=version.id,
            dataset_group=lcfg.get("dataset_group") or group,
            dataset_type="vector",
            name=linfo.name,
            original_format="gpkg" if path.suffix == ".gpkg" else path.suffix.lstrip("."),
            original_crs=crs.to_json(),
            canonical_crs=4326,
            derivation_level=lcfg.get("derivation_level") or default_level,
            review_status=ReviewStatus.PENDING.value,
            quality_state="unchecked",
            source_artifact_id=artifact.id,
        )
        session.add(ds)
        session.flush()
        layer = Layer(
            dataset_id=ds.id,
            canonical_name=lcfg.get("canonical_name") or linfo.name.lower().replace(" ", "_"),
            source_name=linfo.name,
            title=linfo.name,
            thematic_group=lcfg.get("thematic_group"),
            geometry_type=linfo.geometry_type,
            feature_count=0,
            styling_metadata=lcfg.get("style") or {},
        )
        session.add(layer)
        session.flush()

        count = 0
        required = lcfg.get("required_attributes") or []
        field_map = lcfg.get("field_map") or {}
        key_field = lcfg.get("key_field")
        feature_payloads: list[FeaturePayload] = []
        fid_map: dict[str, uuid.UUID] = {}
        for vf in iter_features(path, linfo.name):
            props = dict(vf.properties)
            stable_id = None
            # explicit descriptor key wins; the candidate list is a fallback
            # for foreign data where no descriptor declared a key field
            if key_field and props.get(key_field) not in (None, ""):
                stable_id = str(props[key_field])
            else:
                for cand in ("OBJECTID", "objectid", "id", "ID", "code", "ma_doi_tuong", "MaDT"):
                    if cand in props and props[cand] not in (None, ""):
                        stable_id = str(props[cand])
                        break
            key = stable_id or f"{linfo.name}#{vf.fid if vf.fid is not None else count}"
            geom4326 = None
            if vf.geometry is not None:
                try:
                    geom4326, _transformed = _transform_geom(vf.geometry, crs)
                    if geom4326 is not None and geom4326.has_z:
                        # canonical column is 2D — Z survives in source_geometry_ewkb
                        import shapely

                        geom4326 = shapely.force_2d(geom4326)
                except Exception as exc:
                    geom4326 = None
                    props["_transform_error"] = str(exc)
            mapped = _jsonb_safe({field_map.get(k, k): v for k, v in props.items()})
            classification = (
                mapped.get("classification")
                or mapped.get("land_use")
                or mapped.get("loai_dat")
                or mapped.get("ma_loai_dat")
                or mapped.get("ma_tuyen")
                or mapped.get("type")
            )
            # Features whose geometry can't be canonicalised (unidentified CRS,
            # transform failure) are validated but not persisted — we never
            # write geometry whose provenance is a guess.
            if geom4326 is None:
                feature_payloads.append(
                    FeaturePayload(key=key, geometry=vf.geometry, properties=mapped)
                )
                continue
            feature = Feature(
                layer_id=layer.id,
                stable_external_id=stable_id,
                source_object_code=str(mapped.get("code") or stable_id or "") or None,
                source_object_name=str(mapped.get("name") or mapped.get("ten") or "") or None,
                normalized_name=vn_normalize(str(mapped.get("name") or mapped.get("ten") or "")),
                classification=str(classification) if classification else None,
                geometry=to_postgis(geom4326),
                source_geometry_ewkb=ewkb(vf.geometry, crs.epsg or 0) if vf.geometry else None,
                source_srid=crs.epsg,
                properties=mapped,
            )
            session.add(feature)
            session.flush()
            fid_map[key] = feature.id
            feature_payloads.append(
                FeaturePayload(
                    key=key,
                    geometry=geom4326,
                    properties=mapped,
                    classification=feature.classification,
                )
            )
            count += 1
        layer.feature_count = count

        # validation for this layer
        ctx = ValidationContext(
            dataset_id=str(ds.id),
            dataset_group=ds.dataset_group,
            dataset_type=ds.dataset_type,
            derivation_level=ds.derivation_level,
            original_crs=crs.to_json(),
            artifact_sha256=artifact.content_sha256,
            artifact_recorded_sha256=artifact.content_sha256,
            layers=[
                LayerPayload(
                    name=linfo.name,
                    geometry_type=linfo.geometry_type,
                    expected_geometry_type=lcfg.get("geometry_type"),
                    features=feature_payloads,
                )
            ],
            required_attributes={linfo.name: required},
            planning_version={
                "approval_date": version.approval_date,
                "effective_from": version.effective_from,
                "effective_to": version.effective_to,
                "approval_decision_number": version.approval_decision_number,
            },
            meta={
                "authority": (source_cfg.authority if source_cfg else None),
                "has_provenance": True,
                "topology": {
                    linfo.name: {
                        "no_overlap": bool(lcfg.get("no_overlap")),
                        "no_gaps": bool(lcfg.get("no_gaps")),
                        "no_line_cross": bool(lcfg.get("no_line_cross")),
                    }
                },
            },
        )
        findings = run_rules(ctx)
        persist_findings(
            session,
            findings,
            dataset_id=ds.id,
            run_id=run.id,
            feature_id_map=fid_map,
            layer_id_map={linfo.name: layer.id},
        )
        run.warning_count += sum(1 for f in findings if f.severity in ("warning", "info"))
        if any(f.severity in ("error", "critical") for f in findings):
            ds.quality_state = "errors"

        record_event(
            session,
            entity_type="dataset",
            entity_id=ds.id,
            operation=ProvenanceOp.IMPORTED,
            input_refs=[
                {
                    "entity_type": "artifact",
                    "entity_id": str(artifact.id),
                    "sha256": artifact.content_sha256,
                }
            ],
            tool=TOOL,
            tool_version="0.1.0",
            parameters={
                "layer": linfo.name,
                "crs_epsg": crs.epsg,
                "crs_identified": crs.identified,
            },
            run_id=run.id,
        )
        datasets.append(ds)
    return datasets


def _ingest_raster(
    session: Session,
    artifact: SourceArtifact,
    path: Path,
    version: PlanningVersion,
    source_cfg: SourceConfig | None,
    run: IngestionRun,
) -> Dataset:
    from openquyhoach_geo.raster import inspect_raster

    info = inspect_raster(path)
    parser = source_cfg.parser if source_cfg else {}
    level = parser.get("default_derivation_level") or (
        DerivationLevel.OFFICIAL_RASTER.value
        if info.georeferenced
        else DerivationLevel.DERIVED_MACHINE_UNREVIEWED.value
    )
    ds = Dataset(
        planning_version_id=version.id,
        dataset_group=normalize_group_name(
            (source_cfg.parser.get("default_dataset_group") if source_cfg else None) or "HoSoScan"
        )
        if parser.get("default_dataset_group") != "other"
        else "hoso_gis",
        dataset_type="raster",
        name=artifact.filename,
        original_format=info.driver,
        original_crs=info.crs.to_json(),
        derivation_level=level,
        review_status=ReviewStatus.PENDING.value,
        quality_state="unchecked",
        source_artifact_id=artifact.id,
        meta={"raster": info.to_json()},
    )
    session.add(ds)
    session.flush()
    ctx = ValidationContext(
        dataset_id=str(ds.id),
        dataset_group=ds.dataset_group,
        dataset_type="raster",
        derivation_level=ds.derivation_level,
        original_crs=info.crs.to_json(),
        meta={"authority": source_cfg.authority if source_cfg else None, "has_provenance": True},
    )
    findings = run_rules(ctx)
    persist_findings(session, findings, dataset_id=ds.id, run_id=run.id)
    if not info.georeferenced:
        session.add(
            ReviewTask(
                target_type="dataset",
                target_id=ds.id,
                task_type=TaskType.REVIEW_GEOREFERENCE.value,
                priority=50,
                reason="raster is not georeferenced — create a GeoreferenceJob",
                evidence={"raster": {"width": info.width, "height": info.height}},
            )
        )
    record_event(
        session,
        entity_type="dataset",
        entity_id=ds.id,
        operation=ProvenanceOp.IMPORTED,
        input_refs=[
            {
                "entity_type": "artifact",
                "entity_id": str(artifact.id),
                "sha256": artifact.content_sha256,
            }
        ],
        tool=TOOL,
        tool_version="0.1.0",
        parameters={"driver": info.driver, "georeferenced": info.georeferenced},
        run_id=run.id,
    )
    return ds


def _pdf_hints(info, source_cfg: SourceConfig | None) -> dict:
    """Map PDF candidates onto the planning-hint vocabulary used by
    ``resolve_planning_version``. Only emitted when the descriptor has no
    planning block — official values always win."""
    planning = (source_cfg.meta.get("planning") if source_cfg else None) or {}
    if planning:
        return {}
    c = info.candidate_codes
    hints = {
        "title": c.get("plan_title"),
        "decision_number": c.get("decision_number"),
        "approval_date": c.get("signed_date"),
        "effective_from": c.get("effective_date"),
        "scale": c.get("scale"),
        "approving_authority": c.get("approving_authority"),
        "information_code": c.get("planning_code"),
        "supersedes_decision": c.get("supersedes_decision"),
    }
    return {k: v for k, v in hints.items() if v}


def _ingest_pdf(
    session: Session,
    artifact: SourceArtifact,
    path: Path,
    version: PlanningVersion,
    source_cfg: SourceConfig | None,
    run: IngestionRun,
) -> Document:
    info = inspect_pdf(path)
    hints = _pdf_hints(info, source_cfg)
    if hints:
        # extracted candidates may name a more specific version — re-resolve
        version = resolve_planning_version(session, source_cfg, artifact, hints)

    planning = (source_cfg.meta.get("planning") if source_cfg else None) or {}
    disc = (
        (artifact.meta or {}).get("discovered_metadata", {}).get("planning_hints")
        or {}
    )
    c = info.candidate_codes
    field_origins: dict[str, str] = {}

    document_number = (
        planning.get("decision_number")
        or c.get("decision_number")
        or disc.get("decision_number")
    )
    if document_number:
        field_origins["document_number"] = (
            MetadataOrigin.OFFICIAL_EXPLICIT.value
            if planning.get("decision_number")
            else (
                MetadataOrigin.DERIVED_MACHINE.value
                if c.get("decision_number")
                else MetadataOrigin.DERIVED_DETERMINISTIC.value
            )
        )
    title = info.metadata.get("Title") or planning.get("title") or artifact.filename
    if title:
        field_origins["title"] = (
            MetadataOrigin.DERIVED_DETERMINISTIC.value
            if info.metadata.get("Title")
            else MetadataOrigin.OFFICIAL_EXPLICIT.value
        )
    signed = _parse_date(c.get("signed_date")) or _parse_date(disc.get("approval_date"))
    if signed:
        field_origins["signed_date"] = (
            MetadataOrigin.DERIVED_MACHINE.value
            if c.get("signed_date")
            else MetadataOrigin.DERIVED_DETERMINISTIC.value
        )
    issuing = (
        planning.get("approving_authority")
        or disc.get("approving_authority")
        or (source_cfg.authority if source_cfg else None)
        or c.get("approving_authority")
    )
    if issuing:
        if planning.get("approving_authority") or (source_cfg and source_cfg.authority):
            field_origins["issuing_authority"] = MetadataOrigin.OFFICIAL_EXPLICIT.value
        elif disc.get("approving_authority"):
            field_origins["issuing_authority"] = (
                MetadataOrigin.DERIVED_DETERMINISTIC.value
            )
        else:
            field_origins["issuing_authority"] = MetadataOrigin.DERIVED_MACHINE.value
    # document-level origin = weakest origin used anywhere on the record —
    # machine candidates persisted in meta count as machine-derived
    # metadata even when they are not promoted into fields
    origins = set(field_origins.values())
    if c:
        origins.add(MetadataOrigin.DERIVED_MACHINE.value)
    if MetadataOrigin.DERIVED_MACHINE.value in origins:
        doc_origin = MetadataOrigin.DERIVED_MACHINE.value
    elif MetadataOrigin.UNKNOWN.value in origins:
        doc_origin = MetadataOrigin.UNKNOWN.value
    elif MetadataOrigin.DERIVED_DETERMINISTIC.value in origins:
        doc_origin = MetadataOrigin.DERIVED_DETERMINISTIC.value
    elif origins:
        doc_origin = MetadataOrigin.OFFICIAL_EXPLICIT.value
    else:
        doc_origin = MetadataOrigin.UNKNOWN.value

    doc = Document(
        planning_version_id=version.id,
        artifact_id=artifact.id,
        document_type="approval_decision" if document_number else "document",
        document_number=document_number,
        title=title,
        normalized_title=vn_normalize(title or ""),
        signed_date=signed,
        issuing_authority=issuing,
        metadata_origin=doc_origin,
        page_count=info.page_count,
        meta={
            "pdf_metadata": info.metadata,
            "pages": [vars(p) for p in info.pages[:200]],
            "has_embedded_text": info.has_embedded_text,
            "needs_ocr": info.needs_ocr,
            "candidate_codes": info.candidate_codes,
            "candidates": {k: vars(v) for k, v in info.candidates.items()},
            "field_origins": field_origins,
        },
    )
    session.add(doc)
    session.flush()
    record_event(
        session,
        entity_type="document",
        entity_id=doc.id,
        operation=ProvenanceOp.EXTRACTED,
        input_refs=[
            {
                "entity_type": "artifact",
                "entity_id": str(artifact.id),
                "sha256": artifact.content_sha256,
            }
        ],
        tool="pypdf",
        run_id=run.id,
        parameters={"pages": info.page_count, "embedded_text": info.has_embedded_text},
    )
    if doc_origin == MetadataOrigin.DERIVED_MACHINE.value:
        session.add(
            ReviewTask(
                target_type="document",
                target_id=doc.id,
                task_type=TaskType.REVIEW_METADATA.value,
                priority=55,
                reason="document fields populated by machine extraction — verify against evidence",
                evidence={
                    "field_origins": field_origins,
                    "candidates": {k: vars(v) for k, v in info.candidates.items()},
                },
            )
        )
    if info.needs_ocr:
        session.add(
            ReviewTask(
                target_type="artifact",
                target_id=artifact.id,
                task_type=TaskType.VERIFY_METADATA.value,
                priority=60,
                reason="PDF has no embedded text — OCR is an optional assisted step",
                evidence={"page_count": info.page_count},
            )
        )
    return doc


# ---------------------------------------------------------------------------
# Artifact staging
# ---------------------------------------------------------------------------


def stage_artifact(
    session: Session,
    fetch: FetchResultLike,
    source: Source | None,
    source_cfg: SourceConfig | None,
    run: IngestionRun,
) -> dict:
    """Content-address → store → detect → dispatch. Returns a stage report."""
    report: dict = {"artifact_id": None, "datasets": [], "documents": [], "skipped": False}

    existing = None
    if fetch.sha256:
        existing = (
            session.query(SourceArtifact).filter_by(content_sha256=fetch.sha256).one_or_none()
        )
    if existing is not None:
        report["skipped"] = True
        report["artifact_id"] = str(existing.id)
        record_event(
            session,
            entity_type="artifact",
            entity_id=existing.id,
            operation="unchanged",
            parameters={"reason": "content_sha256 already present"},
            run_id=run.id,
        )
        return report

    head = fetch.local_path.read_bytes()[:512]
    detected = sniff_format(head, fetch.local_path.name)
    key = artifact_key(fetch.sha256, fetch.local_path.name)
    with open(fetch.local_path, "rb") as fh:
        artifact_store().put(key, fh, content_type=fetch.mime_type)

    artifact = SourceArtifact(
        source_id=source.id if source else None,
        canonical_url=fetch.canonical_url,
        retrieved_url=fetch.retrieved_url,
        content_sha256=fetch.sha256,
        mime_type=fetch.mime_type,
        file_size=fetch.size,
        etag=fetch.etag,
        last_modified=fetch.last_modified,
        object_storage_key=key,
        filename=getattr(fetch, "filename", None)
        or _basename(fetch.canonical_url)
        or fetch.local_path.name,
        detected_format=detected,
        status=ArtifactStatus.DOWNLOADED.value,
        meta={"discovered_metadata": getattr(fetch, "metadata", {}) or {}},
    )
    session.add(artifact)
    session.flush()
    report["artifact_id"] = str(artifact.id)
    record_event(
        session,
        entity_type="artifact",
        entity_id=artifact.id,
        operation=ProvenanceOp.DOWNLOADED,
        input_refs=[{"url": fetch.canonical_url}],
        tool=TOOL,
        output_hash=fetch.sha256,
        run_id=run.id,
        parameters={"size": fetch.size, "detected_format": detected},
    )

    # connectors may attach verbatim official planning fields
    # (``discovered_metadata.planning_hints``) — they resolve the artifact
    # to its own record/version at derived_deterministic strength
    disc_hints = (
        (artifact.meta or {}).get("discovered_metadata", {}).get("planning_hints")
        or None
    )
    version = resolve_planning_version(session, source_cfg, artifact, disc_hints)
    dispatch_artifact(session, fetch.local_path, artifact, version, source_cfg, run, report)
    artifact.status = ArtifactStatus.IMPORTED.value
    return report


def _vector_content_digest(session: Session, dataset: Dataset) -> str:
    """Semantic digest of a vector dataset — sorted over every feature's
    (layer, external id, class, properties, WKB). Byte-level upstream
    differences (e.g. GeoServer re-rendering identical features) produce
    the same digest; genuine content changes do not."""
    h = hashlib.sha256()
    rows = session.execute(
        select(
            Layer.canonical_name,
            Feature.stable_external_id,
            Feature.classification,
            Feature.properties,
            func.ST_AsBinary(Feature.geometry),
        )
        .join(Layer, Feature.layer_id == Layer.id)
        .where(Layer.dataset_id == dataset.id)
    ).all()
    for name, ext_id, cls, props, wkb in sorted(
        rows,
        key=lambda r: (
            r[0] or "",
            r[1] or "",
            r[2] or "",
            json.dumps(r[3], sort_keys=True, default=str),
            bytes(r[4] or b""),
        ),
    ):
        h.update((name or "").encode())
        h.update(b"\x00")
        h.update((ext_id or "").encode())
        h.update(b"\x00")
        h.update((cls or "").encode())
        h.update(b"\x00")
        h.update(json.dumps(props, sort_keys=True, default=str).encode())
        h.update(b"\x00")
        h.update(bytes(wkb or b""))
        h.update(b"\x00")
    return h.hexdigest()


def _dedupe_semantic(
    session: Session, datasets: list[Dataset], run: IngestionRun
) -> list[Dataset]:
    """Drop freshly-ingested datasets whose feature content is identical
    to the previous dataset of the same name in the same planning record.

    The new immutable artifact and its observation/change event stay —
    only the redundant derived copy is removed. The now-empty version is
    deleted too when nothing references it."""
    kept: list[Dataset] = []
    for ds in datasets:
        digest = _vector_content_digest(session, ds)
        meta = dict(ds.meta or {})
        meta["content_digest"] = digest
        ds.meta = meta
        prior = session.scalars(
            select(Dataset)
            .join(PlanningVersion, Dataset.planning_version_id == PlanningVersion.id)
            .where(
                Dataset.name == ds.name,
                Dataset.id != ds.id,
                PlanningVersion.planning_record_id
                == ds.planning_version.planning_record_id,
            )
            .order_by(Dataset.created_at.desc())
        ).first()
        prior_digest = (
            (prior.meta or {}).get("content_digest")
            if prior
            else None
        ) or (_vector_content_digest(session, prior) if prior else None)
        if prior is None or prior_digest != digest:
            kept.append(ds)
            continue
        version = ds.planning_version
        for layer in ds.layers:
            session.query(Feature).filter_by(layer_id=layer.id).delete()
            session.delete(layer)
        session.delete(ds)
        session.flush()
        record_event(
            session,
            entity_type="version",
            entity_id=version.id,
            operation="deduplicated",
            run_id=run.id,
            parameters={
                "dataset": ds.name,
                "content_digest": digest,
                "kept_dataset_id": str(prior.id),
            },
        )
        run.deduped_count = getattr(run, "deduped_count", 0) + 1
        remaining_docs = session.scalar(
            select(func.count(Document.id)).where(
                Document.planning_version_id == version.id
            )
        )
        if not version.datasets and not remaining_docs:
            session.delete(version)
    return kept


def _jsonb_safe(obj):
    """Recursively replace NaN/Infinity floats with None.

    GeoJSON/SHP sources routinely carry `NaN` attribute values; Python's
    json module accepts them but PostgreSQL JSONB rejects the token.
    """
    import math

    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _jsonb_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonb_safe(v) for v in obj]
    return obj


def _extract_jsvar_geojson(p: Path) -> Path | None:
    """Unwrap a `var name = {...FeatureCollection...};` JavaScript file.

    Some provincial portals (e.g. quyhoach.hanoi.vn) publish zoning layers
    as JS variable assignments. The raw .js remains the immutable artifact;
    the extracted payload is validated as a GeoJSON FeatureCollection and
    written to a temp file for the normal vector path.
    """
    import re

    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.match(r"\s*var\s+[A-Za-z_$][\w$]*\s*=\s*(\{.*\})\s*;?\s*$", text, re.S)
    if not m:
        return None
    try:
        fc = json.loads(m.group(1))
    except ValueError:
        return None
    if not isinstance(fc, dict) or fc.get("type") != "FeatureCollection" or not isinstance(
        fc.get("features"), list
    ):
        return None
    dest = Path(tempfile.mkdtemp(prefix="oqh-jsvar-")) / f"{p.stem}.geojson"
    dest.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    return dest


def dispatch_artifact(
    session: Session,
    p: Path,
    artifact: SourceArtifact,
    version: PlanningVersion,
    source_cfg: SourceConfig | None,
    run: IngestionRun,
    report: dict,
) -> None:
    """Route a fetched file to the vector/raster/document ingestors.

    Module-level (not a closure) so stored artifacts can be re-dispatched
    without re-downloading — e.g. after a parser/layer-map fix.
    """
    fmt = sniff_format(p.read_bytes()[:512], p.name)
    if fmt == "zip":
        dest = Path(tempfile.mkdtemp(prefix="oqh-zip-"))
        for member in safe_extract_zip(p, dest):
            dispatch_artifact(session, member, artifact, version, source_cfg, run, report)
        return
    if fmt == "jsvar_geojson":
        extracted = _extract_jsvar_geojson(p)
        if extracted is None:
            record_event(
                session,
                entity_type="artifact",
                entity_id=artifact.id,
                operation="skipped",
                run_id=run.id,
                parameters={"reason": "jsvar_geojson payload failed JSON validation"},
            )
            return
        record_event(
            session,
            entity_type="artifact",
            entity_id=artifact.id,
            operation="extracted",
            run_id=run.id,
            parameters={"transform": "jsvar_geojson_strip", "member": extracted.name},
        )
        dispatch_artifact(session, extracted, artifact, version, source_cfg, run, report)
        return
    if is_dwg(p):
        record_event(
            session,
            entity_type="artifact",
            entity_id=artifact.id,
            operation="rejected",
            run_id=run.id,
            parameters={"reason": "dwg_unsupported_convert_to_dxf_or_gpkg"},
        )
        session.add(
            ReviewTask(
                target_type="artifact",
                target_id=artifact.id,
                task_type=TaskType.CURATE_SOURCE.value,
                priority=80,
                reason="DWG file detected — convert to DXF/GeoPackage before ingest",
            )
        )
        return
    if fmt in VECTOR_FORMATS or is_vector_file(p):
        try:
            datasets = _ingest_vector(session, artifact, p, version, source_cfg, run)
            datasets = _dedupe_semantic(session, datasets, run)
            report["datasets"].extend(str(d.id) for d in datasets)
            run.imported_count += len(datasets)
        except UnsupportedFormatError as exc:
            record_event(
                session,
                entity_type="artifact",
                entity_id=artifact.id,
                operation="rejected",
                run_id=run.id,
                parameters={"reason": str(exc)},
            )
            run.rejected_count += 1
        return
    if fmt in RASTER_FORMATS:
        ds = _ingest_raster(session, artifact, p, version, source_cfg, run)
        report["datasets"].append(str(ds.id))
        run.imported_count += 1
        return
    if fmt in DOC_FORMATS:
        doc = _ingest_pdf(session, artifact, p, version, source_cfg, run)
        report["documents"].append(str(doc.id))
        return
    record_event(
        session,
        entity_type="artifact",
        entity_id=artifact.id,
        operation="skipped",
        run_id=run.id,
        parameters={"reason": f"unhandled format {fmt}"},
    )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def _source_row(session: Session, source_key: str | None) -> Source | None:
    if not source_key:
        return None
    return session.query(Source).filter_by(source_key=source_key).one_or_none()


def ingest_source(
    source_key: str,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    workdir: Path | None = None,
) -> uuid.UUID:
    """Full pipeline for one registered source.

    Delegates to the crawl runner (openquyhoach_ingest.crawl.sync_source)
    which adds persistent crawl state, conditional fetching and upstream
    change detection on top of the staging pipeline below.
    """
    from .crawl import sync_source

    return sync_source(
        source_key, trigger="cli", limit=limit, workdir=workdir, dry_run=dry_run
    )


def ingest_path(
    path: str | Path,
    *,
    source_key: str | None = None,
    planning: dict | None = None,
    dry_run: bool = False,
) -> uuid.UUID:
    """Ad-hoc single-file ingest (community imports, tests)."""
    cfg = load_config(source_key) if source_key else None
    if planning:
        cfg = cfg or SourceConfig(key="adhoc", name="adhoc", source_type="file")
        cfg.meta["planning"] = planning
    p = Path(path).resolve()
    with session_scope() as session:
        source = _source_row(session, source_key)
        run = IngestionRun(
            source_id=source.id if source else None,
            trigger="cli",
            software_commit=_git_commit(),
            status=IngestionStatus.RUNNING.value,
            meta={"dry_run": dry_run, "path": str(p)},
        )
        session.add(run)
        session.flush()
        try:
            sha, size = sha256_file(p)
            fetch = _LocalFetch(p, p.as_uri(), sha, size)
            run.discovered_count = 1
            if not dry_run:
                stage_artifact(session, fetch, source, cfg, run)
                run.downloaded_count = 1
            run.status = IngestionStatus.SUCCEEDED.value
        except Exception as exc:
            run.status = IngestionStatus.FAILED.value
            run.error_summary = str(exc)[:4000]
            raise
        finally:
            run.completed_at = datetime.now(UTC)
        return run.id


def ingest_url(
    url: str,
    *,
    source_key: str | None = None,
    planning: dict | None = None,
    dry_run: bool = False,
) -> uuid.UUID:
    """Ad-hoc URL ingest through the HTTP machinery (SSRF-guarded)."""
    from .http_client import fetch_url

    cfg = load_config(source_key) if source_key else None
    if planning:
        cfg = cfg or SourceConfig(key="adhoc", name="adhoc", source_type="http")
        cfg.meta["planning"] = planning
    with session_scope() as session:
        source = _source_row(session, source_key)
        run = IngestionRun(
            source_id=source.id if source else None,
            trigger="cli",
            software_commit=_git_commit(),
            status=IngestionStatus.RUNNING.value,
            meta={"dry_run": dry_run, "url": url},
        )
        session.add(run)
        session.flush()
        try:
            if not dry_run:
                wd = Path(tempfile.mkdtemp(prefix="oqh-url-"))
                res = fetch_url(url, wd)
                fetch = _LocalFetch(
                    res["local_path"],
                    url,
                    res["sha256"],
                    res["size"],
                    mime=res.get("mime_type"),
                    etag=res.get("etag"),
                    last_modified=res.get("last_modified"),
                )
                run.downloaded_count = 1
                stage_artifact(session, fetch, source, cfg, run)
            run.discovered_count = 1
            run.status = IngestionStatus.SUCCEEDED.value
        except Exception as exc:
            run.status = IngestionStatus.FAILED.value
            run.error_summary = str(exc)[:4000]
            raise
        finally:
            run.completed_at = datetime.now(UTC)
        return run.id


class _LocalFetch:
    """Minimal FetchResult-compatible wrapper for local paths/URL results."""

    def __init__(
        self,
        path: Path,
        url: str,
        sha: str,
        size: int,
        mime: str | None = None,
        etag=None,
        last_modified=None,
    ):
        self.local_path = path
        self.canonical_url = url
        self.retrieved_url = url
        self.sha256 = sha
        self.size = size
        self.mime_type = mime
        self.etag = etag
        self.last_modified = last_modified
        self.filename = _basename(url) or path.name
        self.metadata: dict = {}


FetchResultLike = _LocalFetch | FetchResult
