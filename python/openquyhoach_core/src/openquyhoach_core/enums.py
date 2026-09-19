"""Canonical enumerations. String values are part of the public contract."""

from __future__ import annotations

import enum

StrEnum = enum.StrEnum


class DerivationLevel(StrEnum):
    """How a spatial object relates to official source material.

    The single most important field for the "never blur official and derived"
    principle. Every published layer carries exactly one of these.
    """

    OFFICIAL_VECTOR = "official_vector"
    OFFICIAL_RASTER = "official_raster"
    OFFICIAL_DOCUMENT = "official_document"
    DERIVED_HUMAN_REVIEWED = "derived_human_reviewed"
    DERIVED_MACHINE_REVIEWED = "derived_machine_reviewed"
    DERIVED_MACHINE_UNREVIEWED = "derived_machine_unreviewed"
    REFERENCE_APPROXIMATE = "reference_approximate"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class QualitySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ArtifactStatus(StrEnum):
    DOWNLOADED = "downloaded"
    INSPECTED = "inspected"
    IMPORTED = "imported"
    REJECTED = "rejected"
    FAILED = "failed"


class SourceType(StrEnum):
    FILE = "file"
    HTTP = "http"
    HTML_INDEX = "html_index"
    ARCGIS_REST = "arcgis_rest"
    OGC_WMS = "ogc_wms"
    OGC_WFS = "ogc_wfs"
    PLANNING_PORTAL = "planning_portal"
    DOCUMENT_REPOSITORY = "document_repository"


class DatasetGroup(StrEnum):
    """Groups corresponding to the Vietnamese planning GIS framework."""

    NEN_DIA_HINH = "nen_dia_hinh"  # base terrain
    HIEN_TRANG = "hien_trang"  # existing conditions
    QUY_HOACH = "quy_hoach"  # planning
    MOC_GIOI = "moc_gioi"  # demarcation markers
    HOSO_GIS = "hoso_gis"  # unclassified GIS package member
    OTHER = "other"


class DatasetType(StrEnum):
    VECTOR = "vector"
    RASTER = "raster"
    DOCUMENT = "document"


class LegalStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    AMENDED = "amended"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class VersionKind(StrEnum):
    ORIGINAL = "original"
    AMENDMENT = "amendment"
    ADJUSTMENT = "adjustment"
    REPLACEMENT = "replacement"


class IngestionStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class ProvenanceOp(StrEnum):
    DOWNLOADED = "downloaded"
    EXTRACTED = "extracted"
    OCRED = "ocred"
    VECTORIZED = "vectorized"
    REPROJECTED = "reprojected"
    SIMPLIFIED = "simplified"
    GEOREFERENCED = "georeferenced"
    HUMAN_REVIEWED = "human_reviewed"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    VALIDATED = "validated"
    NORMALIZED = "normalized"
    IMPORTED = "imported"


class ActorType(StrEnum):
    SYSTEM = "system"
    HUMAN = "human"
    AI = "ai"


class GeorefStatus(StrEnum):
    DRAFT = "draft"
    COMPUTED = "computed"
    APPROVED = "approved"
    REJECTED = "rejected"


class TransformType(StrEnum):
    AFFINE = "affine"
    POLYNOMIAL_2 = "polynomial_2"
    POLYNOMIAL_3 = "polynomial_3"
    PROJECTIVE = "projective"
    TPS = "tps"


class PublicationStatus(StrEnum):
    BUILDING = "building"
    PUBLISHED = "published"
    FAILED = "failed"
    WITHDRAWN = "withdrawn"


class TaskType(StrEnum):
    REVIEW_DATASET = "review_dataset"
    REVIEW_GEOREFERENCE = "review_georeference"
    FIX_QUALITY = "fix_quality"
    VERIFY_METADATA = "verify_metadata"
    CURATE_SOURCE = "curate_source"
    REVIEW_METADATA = "review_metadata"
    REVIEW_SOURCE = "review_source"


class SourceHealth(StrEnum):
    """Operational health of a configured source — derived from crawl state,
    never confused with "no upstream changes"."""

    UNKNOWN = "unknown"  # never checked
    HEALTHY = "healthy"  # first successful check
    UNCHANGED = "unchanged"  # successful check, nothing new
    CHANGED = "changed"  # successful check, upstream changes detected
    DEGRADED = "degraded"  # partial failures or intermittent errors
    FAILING = "failing"  # consecutive failures past threshold
    BLOCKED = "blocked"  # robots/policy/403 — we must not fetch
    DISABLED = "disabled"  # descriptor disabled
    NEEDS_REVIEW = "needs_review"  # pending review tasks against this source


class ResourceStatus(StrEnum):
    ACTIVE = "active"
    DISAPPEARED = "disappeared"
    ERROR = "error"


class ObservationOutcome(StrEnum):
    """What a single resource check observed."""

    SEEN_NEW = "seen_new"  # first observation of this resource
    SEEN_UNCHANGED = "seen_unchanged"  # bytes identical to last observation
    SEEN_CHANGED = "seen_changed"  # bytes differ — new artifact revision
    NOT_MODIFIED = "not_modified"  # server 304 to conditional request
    DISAPPEARED = "disappeared"  # previously seen, absent from discovery
    ERROR = "error"  # fetch failed
    BLOCKED = "blocked"  # robots/policy denied


class ChangeType(StrEnum):
    """Upstream change classification for source_change_events."""

    ADDED = "added"
    DISAPPEARED = "disappeared"
    REAPPEARED = "reappeared"
    CHECKSUM_CHANGED = "checksum_changed"
    URL_CHANGED = "url_changed"
    METADATA_CHANGED = "metadata_changed"


class MetadataOrigin(StrEnum):
    """Where a metadata field's value came from. Machine-derived values must
    never silently become official metadata."""

    OFFICIAL_EXPLICIT = "official_explicit"  # stated by the authority/descriptor
    DERIVED_DETERMINISTIC = "derived_deterministic"  # rule-based, reproducible
    DERIVED_MACHINE = "derived_machine"  # regex/ML extraction — needs review
    HUMAN_REVIEWED = "human_reviewed"  # confirmed by a reviewer
    UNKNOWN = "unknown"
