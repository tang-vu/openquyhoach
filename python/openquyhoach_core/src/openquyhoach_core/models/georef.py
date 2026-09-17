from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class GeoreferenceJob(Base):
    """A georeferencing session for one source raster.

    `gcps` holds the full control-point set (accepted + rejected, with
    residuals); `suggestions` holds machine-proposed GCPs that were
    NOT adopted — kept for audit."""

    __tablename__ = "georeference_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_artifacts.id"))
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("datasets.id"))
    transform_type: Mapped[str] = mapped_column(String(32), default="affine")
    target_srid: Mapped[int] = mapped_column(Integer, default=4326)
    gcps: Mapped[list] = mapped_column(JSONB, default=list)
    # [{"id","pixel_x","pixel_y","map_x","map_y","enabled","residual","origin"}]
    suggestions: Mapped[list] = mapped_column(JSONB, default=list)
    detected_labels: Mapped[dict] = mapped_column(JSONB, default=dict)
    rmse: Mapped[float | None] = mapped_column(Float)
    residuals: Mapped[dict] = mapped_column(JSONB, default=dict)
    transform_coefficients: Mapped[list | None] = mapped_column(JSONB)
    output_storage_key: Mapped[str | None] = mapped_column(Text)  # resulting COG
    output_sha256: Mapped[str | None] = mapped_column(String(64))
    algorithm: Mapped[str | None] = mapped_column(String(128))
    suggestion_source: Mapped[str | None] = mapped_column(String(64))  # manual|ocr|ai|import
    review_status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    reviewer: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
