from __future__ import annotations

import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class ChangeSet(Base):
    """A computed diff between two compatible layers (typically the same
    canonical layer across two planning versions)."""

    __tablename__ = "change_sets"
    __table_args__ = (Index("ix_changeset_pair", "from_layer_id", "to_layer_id", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    from_layer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("layers.id"))
    to_layer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("layers.id"))
    algorithm: Mapped[str] = mapped_column(String(128), default="keyed-geom-diff-v1")
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    # {added, removed, geometry_changed, classification_changed, properties_changed,
    #  added_area_m2, removed_area_m2, modified_area_m2}
    computed_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    entries: Mapped[list[ChangeSetEntry]] = relationship(
        back_populates="change_set", cascade="all, delete-orphan"
    )


class ChangeSetEntry(Base):
    __tablename__ = "change_set_entries"
    __table_args__ = (Index("ix_changeset_entries_set", "change_set_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    change_set_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("change_sets.id"))
    change_type: Mapped[str] = mapped_column(
        String(32)
    )  # added|removed|geometry_changed|classification_changed|properties_changed
    from_feature_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("features.id"))
    to_feature_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("features.id"))
    match_key: Mapped[str | None] = mapped_column(String(255))  # stable_external_id used to pair
    delta_area_m2: Mapped[float | None] = mapped_column()
    geometry = mapped_column(Geometry(geometry_type="GEOMETRY", srid=4326), nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    change_set: Mapped[ChangeSet] = relationship(back_populates="entries")
