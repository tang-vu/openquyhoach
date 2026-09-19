"""Operational crawl state — mutable runtime state kept *out of* the
immutable source descriptors.

Three cooperating tables:

* ``source_resources`` — the deduplicated inventory of candidate resources
  a source has ever offered (identity = source_id + resource_key).
* ``source_observations`` — append-only log: every check of every resource.
* ``source_crawl_state`` — one row per source answering "when last checked /
  changed / successful, how many consecutive failures, what's the health".
* ``source_change_events`` — first-class upstream change records
  (added / disappeared / checksum_changed / ...).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class SourceResource(Base):
    """One candidate resource discovered from a source (a downloadable URL).

    Identity is ``(source_id, resource_key)`` where ``resource_key`` is a
    stable hash of the canonical URL plus any identity parameters the
    connector supplies. A URL that disappears stays in the table with
    ``status='disappeared'`` — history is never erased.
    """

    __tablename__ = "source_resources"
    __table_args__ = (
        Index("uq_source_resources_key", "source_id", "resource_key", unique=True),
        Index("ix_source_resources_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), index=True)
    resource_key: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text, index=True)
    title: Mapped[str | None] = mapped_column(Text)
    discovered_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    http_status: Mapped[int | None] = mapped_column(Integer)
    etag: Mapped[str | None] = mapped_column(String(512))
    last_modified: Mapped[str | None] = mapped_column(String(255))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceObservation(Base):
    """Append-only log entry — one row per resource-check per run."""

    __tablename__ = "source_observations"
    __table_args__ = (
        Index("ix_source_obs_source_time", "source_id", "observed_at"),
        Index("ix_source_obs_resource", "resource_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), index=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_resources.id"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    http_status: Mapped[int | None] = mapped_column(Integer)
    etag: Mapped[str | None] = mapped_column(String(512))
    last_modified: Mapped[str | None] = mapped_column(String(255))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)


class SourceCrawlState(Base):
    """One row per source — the operational dashboard answer."""

    __tablename__ = "source_crawl_state"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id"), primary_key=True
    )
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_change_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    last_http_status: Mapped[int | None] = mapped_column(Integer)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    health: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    resources_seen: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    lock_token: Mapped[str | None] = mapped_column(String(64))
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SourceChangeEvent(Base):
    """First-class record of an upstream change detected during a sync."""

    __tablename__ = "source_change_events"
    __table_args__ = (
        Index("ix_change_events_source_time", "source_id", "detected_at"),
        Index("ix_change_events_type", "change_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_resources.id"))
    change_type: Mapped[str] = mapped_column(String(32))
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    from_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_artifacts.id")
    )
    to_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
