from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Publication(Base):
    """An immutable published snapshot of a dataset/planning version —
    PMTiles archive + manifest, content-addressed by checksum."""

    __tablename__ = "publications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    planning_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("planning_versions.id"), index=True
    )
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("datasets.id"))
    status: Mapped[str] = mapped_column(String(32), default="building")
    artifact_key: Mapped[str | None] = mapped_column(Text)  # pmtiles object key
    manifest_key: Mapped[str | None] = mapped_column(Text)
    manifest: Mapped[dict] = mapped_column(JSONB, default=dict)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    feature_count: Mapped[int | None] = mapped_column(BigInteger)
    bbox: Mapped[list | None] = mapped_column(JSONB)  # [minx,miny,maxx,maxy] WGS84
    min_zoom: Mapped[int | None] = mapped_column(Integer)
    max_zoom: Mapped[int | None] = mapped_column(Integer)
    software_commit: Mapped[str | None] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
