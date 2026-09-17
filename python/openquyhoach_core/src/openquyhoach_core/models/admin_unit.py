from __future__ import annotations

import uuid
from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class AdministrativeUnit(Base):
    """A Vietnamese administrative unit — temporally versioned because
    boundaries and codes change (mergers, splits, renames). `level` is a
    free-form rank (province/district/commune/ward...) — the hierarchy is
    data-driven via `parent_id`, never hard-coded."""

    __tablename__ = "administrative_units"
    __table_args__ = (
        Index("ix_admin_units_code_valid", "official_code", "valid_from", "valid_to"),
        Index("ix_admin_units_name", "normalized_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    official_code: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(512))
    normalized_name: Mapped[str] = mapped_column(String(512))
    level: Mapped[str] = mapped_column(String(64))  # province|district|commune|special...
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("administrative_units.id"))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    geometry = mapped_column(Geometry(geometry_type="MULTIPOLYGON", srid=4326), nullable=True)
    source: Mapped[str | None] = mapped_column(Text)
    source_version: Mapped[str | None] = mapped_column(String(128))
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
