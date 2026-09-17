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
