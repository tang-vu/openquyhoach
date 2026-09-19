from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class Authority(Base):
    """An issuing/publishing authority (Bộ, Sở, UBND, institute...)."""

    __tablename__ = "authorities"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    canonical_name: Mapped[str] = mapped_column(String(512))
    normalized_name: Mapped[str] = mapped_column(String(512), index=True)
    authority_type: Mapped[str] = mapped_column(String(64))  # ministry|province|district|agency...
    jurisdiction: Mapped[str | None] = mapped_column(String(128), index=True)
    official_domain: Mapped[str | None] = mapped_column(String(255))
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sources: Mapped[list[Source]] = relationship(back_populates="authority")


class Source(Base):
    """A configured data source — backed by a YAML descriptor in sources/."""

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_key: Mapped[str] = mapped_column(String(255), unique=True)  # e.g. "demo/demo-district"
    authority_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("authorities.id"))
    name: Mapped[str] = mapped_column(String(512))
    source_type: Mapped[str] = mapped_column(String(64))
    base_url: Mapped[str | None] = mapped_column(Text)
    jurisdiction: Mapped[str | None] = mapped_column(String(128), index=True)
    terms_url: Mapped[str | None] = mapped_column(Text)
    rights_statement: Mapped[str | None] = mapped_column(Text)
    license: Mapped[str | None] = mapped_column(String(255))
    redistribution_status: Mapped[str] = mapped_column(String(64), default="unknown")
    crawl_policy: Mapped[dict] = mapped_column(JSONB, default=dict)
    descriptor: Mapped[dict] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(default=100)
    admin_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("administrative_units.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    authority: Mapped[Authority | None] = relationship(back_populates="sources")
