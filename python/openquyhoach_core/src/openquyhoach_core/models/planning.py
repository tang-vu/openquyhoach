from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base

if TYPE_CHECKING:
    from .dataset import Dataset


class PlanningRecord(Base):
    """A logical planning instrument (đồ án quy hoạch). Temporal/legal
    snapshots live in :class:`PlanningVersion`."""

    __tablename__ = "planning_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    official_information_code: Mapped[str | None] = mapped_column(
        String(128), index=True
    )  # mã thông tin quy hoạch
    official_file_code: Mapped[str | None] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(Text)
    normalized_title: Mapped[str] = mapped_column(Text, index=True)
    planning_type: Mapped[str | None] = mapped_column(
        String(128), index=True
    )  # quy_hoach_chung|quy_hoach_phan_khu|...
    scale: Mapped[str | None] = mapped_column(String(64))  # 1/500, 1/2000, 1/5000...
    jurisdiction: Mapped[str | None] = mapped_column(String(255), index=True)
    location_description: Mapped[str | None] = mapped_column(Text)
    approving_authority: Mapped[str | None] = mapped_column(String(512))
    consultant: Mapped[str | None] = mapped_column(String(512))
    investor: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(64), default="active")
    keywords: Mapped[list] = mapped_column(JSONB, default=list)
    admin_unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("administrative_units.id"))
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list[PlanningVersion]] = relationship(
        back_populates="record", order_by="PlanningVersion.effective_from"
    )


class PlanningVersion(Base):
    """One temporal/legal state of a planning record. Never overwritten —
    amendments create new versions that supersede the previous one."""

    __tablename__ = "planning_versions"
    __table_args__ = (
        Index("ix_planning_versions_record_effective", "planning_record_id", "effective_from"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    planning_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("planning_records.id"), index=True
    )
    version_kind: Mapped[str] = mapped_column(String(64), default="original")
    version_label: Mapped[str | None] = mapped_column(String(128))
    approval_decision_number: Mapped[str | None] = mapped_column(String(128), index=True)
    approval_date: Mapped[date | None] = mapped_column(Date)
    effective_from: Mapped[date | None] = mapped_column(Date, index=True)
    effective_to: Mapped[date | None] = mapped_column(Date)
    legal_status: Mapped[str] = mapped_column(String(64), default="unknown")
    supersedes_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("planning_versions.id")
    )
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    record: Mapped[PlanningRecord] = relationship(back_populates="versions")
    datasets: Mapped[list[Dataset]] = relationship(back_populates="planning_version")


class Document(Base):
    """A document attached to a planning version (decision, report, map book...)."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    planning_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("planning_versions.id"), index=True
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    document_type: Mapped[str | None] = mapped_column(
        String(64), index=True
    )  # approval_decision|report|map_book|appendix|scan
    document_number: Mapped[str | None] = mapped_column(String(128), index=True)
    title: Mapped[str | None] = mapped_column(Text)
    normalized_title: Mapped[str | None] = mapped_column(Text, index=True)
    signed_date: Mapped[date | None] = mapped_column(Date)
    issuing_authority: Mapped[str | None] = mapped_column(String(512))
    page_count: Mapped[int | None] = mapped_column(Integer)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
