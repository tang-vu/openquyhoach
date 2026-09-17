from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class SourceArtifact(Base):
    """An immutable, content-addressed download. Never mutated after insert —
    a changed upstream file produces a *new* artifact row (new sha256)."""

    __tablename__ = "source_artifacts"
    __table_args__ = (
        Index("ix_source_artifacts_source_sha", "source_id", "content_sha256"),
        Index("ix_source_artifacts_url", "canonical_url"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))
    canonical_url: Mapped[str | None] = mapped_column(Text)
    retrieved_url: Mapped[str | None] = mapped_column(Text)
    retrieval_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    etag: Mapped[str | None] = mapped_column(String(255))
    last_modified: Mapped[str | None] = mapped_column(String(255))
    object_storage_key: Mapped[str] = mapped_column(Text)
    filename: Mapped[str | None] = mapped_column(String(512))
    detected_format: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="downloaded")
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
