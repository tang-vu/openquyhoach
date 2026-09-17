from __future__ import annotations

import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class QualityObservation(Base):
    """One finding from the validation engine. `rule_code` is stable and
    individually addressable (see openquyhoach_quality.rules)."""

    __tablename__ = "quality_observations"
    __table_args__ = (
        Index("ix_quality_target", "target_type", "target_id"),
        Index("ix_quality_rule", "rule_code"),
        Index("ix_quality_open", "resolved_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    target_type: Mapped[str] = mapped_column(String(32))  # dataset|layer|feature
    target_id: Mapped[uuid.UUID] = mapped_column()
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    rule_code: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    geometry = mapped_column(Geometry(geometry_type="GEOMETRY", srid=4326), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReviewTask(Base):
    """Human review gate item — nothing derived reaches 'published'
    without passing through here when policy requires review."""

    __tablename__ = "review_tasks"
    __table_args__ = (Index("ix_review_target", "target_type", "target_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    target_type: Mapped[str] = mapped_column(String(64))  # dataset|georef_job|artifact|source
    target_id: Mapped[uuid.UUID] = mapped_column()
    task_type: Mapped[str] = mapped_column(String(64))
    priority: Mapped[int] = mapped_column(default=100)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(255))
    reason: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    resolution: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
