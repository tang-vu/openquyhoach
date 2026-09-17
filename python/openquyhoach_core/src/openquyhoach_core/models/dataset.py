from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from geoalchemy2 import Geometry
from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base

if TYPE_CHECKING:
    from .planning import PlanningVersion


class Dataset(Base):
    """One logical GIS/raster/document dataset inside a planning version."""

    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    planning_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("planning_versions.id"), index=True
    )
    dataset_group: Mapped[str] = mapped_column(
        String(64), index=True
    )  # nen_dia_hinh|hien_trang|quy_hoach|moc_gioi|hoso_gis|other
    dataset_type: Mapped[str] = mapped_column(String(32))  # vector|raster|document
    name: Mapped[str | None] = mapped_column(String(512))
    original_format: Mapped[str | None] = mapped_column(String(64))
    original_crs: Mapped[dict] = mapped_column(JSONB, default=dict)  # {epsg,wkt,projjson,raw}
    canonical_crs: Mapped[int] = mapped_column(Integer, default=4326)
    derivation_level: Mapped[str] = mapped_column(String(64), index=True)
    review_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    quality_state: Mapped[str] = mapped_column(String(32), default="unchecked")
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    storage_key: Mapped[str | None] = mapped_column(Text)  # normalized output (COG/GPKG)
    published: Mapped[bool] = mapped_column(default=False)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    planning_version: Mapped[PlanningVersion] = relationship(back_populates="datasets")
    layers: Mapped[list[Layer]] = relationship(back_populates="dataset")


class Layer(Base):
    __tablename__ = "layers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id"), index=True)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    source_name: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(512))
    thematic_group: Mapped[str | None] = mapped_column(String(128), index=True)
    geometry_type: Mapped[str | None] = mapped_column(String(64))
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    styling_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dataset: Mapped[Dataset] = relationship(back_populates="layers")


class Feature(Base):
    """A spatial feature. `geometry` is canonical EPSG:4326; the untransformed
    source geometry is preserved losslessly as EWKB in `source_geometry_ewkb`.
    Frequently-queried attributes are promoted to typed columns — `properties`
    keeps the complete source attribute set."""

    __tablename__ = "features"
    __table_args__ = (
        Index("ix_features_layer_code", "layer_id", "source_object_code"),
        Index("ix_features_class", "classification"),
        Index("ix_features_valid", "valid_from", "valid_to"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    layer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("layers.id"), index=True)
    stable_external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    source_object_code: Mapped[str | None] = mapped_column(String(255))
    source_object_name: Mapped[str | None] = mapped_column(String(512))
    normalized_name: Mapped[str | None] = mapped_column(String(512), index=True)
    classification: Mapped[str | None] = mapped_column(String(255))
    geometry = mapped_column(Geometry(geometry_type="GEOMETRY", srid=4326), nullable=False)
    source_geometry_ewkb: Mapped[bytes | None] = mapped_column(LargeBinary)
    source_srid: Mapped[int | None] = mapped_column(Integer)
    area_m2: Mapped[float | None] = mapped_column()
    properties: Mapped[dict] = mapped_column(JSONB, default=dict)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    lineage: Mapped[dict] = mapped_column(JSONB, default=dict)  # {artifact_id, run_id, ...}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    layer: Mapped[Layer] = relationship()


# GiST index created in migration via DDL (geoalchemy2 emits it automatically,
# but keeping it explicit in the migration makes intent clear).
