from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class ProvenanceEvent(Base):
    """One recorded transformation/observation in an entity's lineage."""

    __tablename__ = "provenance_events"
    __table_args__ = (
        Index("ix_provenance_target", "entity_type", "entity_id"),
        Index("ix_provenance_run", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(
        String(64)
    )  # artifact|document|dataset|layer|feature|georef_job|publication|planning_version
    entity_id: Mapped[uuid.UUID] = mapped_column()
    operation: Mapped[str] = mapped_column(String(64))
    input_refs: Mapped[list] = mapped_column(
        JSONB, default=list
    )  # [{"entity_type": ..., "entity_id": ..., "sha256": ...}]
    tool: Mapped[str | None] = mapped_column(String(128))
    tool_version: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))  # AI model id, when relevant
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict)
    output_hash: Mapped[str | None] = mapped_column(String(64))
    actor_type: Mapped[str] = mapped_column(String(32), default="system")
    actor: Mapped[str | None] = mapped_column(String(255))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))
    trigger: Mapped[str] = mapped_column(String(64), default="cli")  # cli|api|schedule|manual
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    software_commit: Mapped[str | None] = mapped_column(String(64))
    configuration_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    downloaded_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
