from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class CoverageSummary(Base):
    """What OpenQuyHoach knows about an administrative unit — deliberately
    distinguishable from "no planning exists"."""

    __tablename__ = "coverage_summaries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    admin_unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("administrative_units.id"), index=True
    )
    state: Mapped[str] = mapped_column(String(64), default="no_source_discovered")
    # no_source_discovered|source_discovered|documents_indexed|raster_available|
    # gis_available|reviewed
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    document_count: Mapped[int] = mapped_column(Integer, default=0)
    dataset_count: Mapped[int] = mapped_column(Integer, default=0)
    reviewed_count: Mapped[int] = mapped_column(Integer, default=0)
    last_checked: Mapped[date | None] = mapped_column(Date)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
