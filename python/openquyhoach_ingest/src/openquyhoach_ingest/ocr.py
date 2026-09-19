"""Assisted OCR for scanned planning documents.

OCR is an *optional aid*, never authoritative evidence. Every OCR-derived
field stays ``derived_machine``, keeps page/snippet evidence, and the
document retains (or gains) a metadata review task. The original scanned
artifact is immutable and untouched — OCR output lives on the Document's
``meta['ocr']`` block with a text hash.

External binaries required: ``pdftoppm`` (poppler) and ``tesseract`` with
the ``vie`` traineddata. Missing binaries make :func:`ocr_available`
return ``False``; callers should skip rather than fail.
"""

from __future__ import annotations

import contextlib
import hashlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from openquyhoach_core.enums import MetadataOrigin, ProvenanceOp, TaskType
from openquyhoach_core.models import Document, ReviewTask, SourceArtifact
from openquyhoach_core.provenance import record_event
from openquyhoach_core.storage import artifact_store
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .pdfmeta import Candidate, extract_candidates

if TYPE_CHECKING:
    from openquyhoach_core.models import IngestionRun

DEFAULT_DPI = 200
DEFAULT_LANG = "vie+eng"
DEFAULT_MAX_PAGES = 8
OCR_TIMEOUT = 180
MAX_TEXT_STORED = 60_000


@dataclass
class OcrResult:
    page_texts: list[str]
    engine: str
    lang: str
    dpi: int
    candidates: dict[str, Candidate] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(self.page_texts)


def ocr_available() -> bool:
    """True when both external binaries needed for OCR are on PATH."""
    return shutil.which("pdftoppm") is not None and shutil.which("tesseract") is not None


def _tesseract_version() -> str:
    try:
        out = subprocess.run(
            ["tesseract", "--version"], capture_output=True, text=True, timeout=10
        )
        return (out.stdout or "").splitlines()[0].strip() or "tesseract"
    except Exception:
        return "tesseract"


def ocr_pdf(
    path: str | Path,
    *,
    dpi: int = DEFAULT_DPI,
    lang: str = DEFAULT_LANG,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> OcrResult:
    """Render + OCR the first ``max_pages`` pages of a scanned PDF."""
    if not ocr_available():
        raise RuntimeError("OCR requires pdftoppm (poppler) and tesseract on PATH")
    p = Path(path)
    work = Path(tempfile.mkdtemp(prefix="oqh-ocr-"))
    try:
        prefix = work / "page"
        subprocess.run(
            [
                "pdftoppm",
                "-r",
                str(dpi),
                "-png",
                "-f",
                "1",
                "-l",
                str(max_pages),
                str(p),
                str(prefix),
            ],
            check=True,
            capture_output=True,
            timeout=OCR_TIMEOUT,
        )
        page_texts: list[str] = []
        for img in sorted(work.glob("page-*.png")):
            out = subprocess.run(
                ["tesseract", str(img), "stdout", "-l", lang, "--psm", "6"],
                capture_output=True,
                text=True,
                timeout=OCR_TIMEOUT,
            )
            page_texts.append(out.stdout or "")
        engine = f"tesseract/{_tesseract_version()}"
        return OcrResult(
            page_texts=page_texts,
            engine=engine,
            lang=lang,
            dpi=dpi,
            candidates=extract_candidates(page_texts),
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _field_updates(doc: Document, candidates: dict[str, Candidate]) -> dict[str, str]:
    """Fill *empty* document fields from OCR candidates — never overwrite."""
    updates: dict[str, str] = {}
    if not doc.document_number and "decision_number" in candidates:
        updates["document_number"] = candidates["decision_number"].value
    if doc.signed_date is None and "signed_date" in candidates:
        with contextlib.suppress(ValueError):
            updates["signed_date"] = datetime.fromisoformat(
                candidates["signed_date"].value
            ).date()
    if not doc.issuing_authority and "approving_authority" in candidates:
        updates["issuing_authority"] = candidates["approving_authority"].value
    return updates


def ocr_document(
    session: Session,
    doc: Document,
    *,
    run: IngestionRun | None = None,
    dpi: int = DEFAULT_DPI,
    lang: str = DEFAULT_LANG,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> dict:
    """OCR one scanned document; returns a small stats dict.

    Writes ``meta['ocr']`` with engine/params/text-hash and OCR-derived
    candidates (with evidence). Empty document fields are filled and
    marked ``derived_machine``; a metadata review task is ensured.
    """
    artifact = session.get(SourceArtifact, doc.artifact_id)
    if artifact is None or not artifact.object_storage_key:
        raise ValueError(f"document {doc.id} has no retrievable artifact")
    payload = artifact_store().get(artifact.object_storage_key)
    with tempfile.NamedTemporaryFile(
        suffix=".pdf", prefix="oqh-ocr-", delete=False
    ) as fh:
        fh.write(payload)
        tmp = Path(fh.name)
    try:
        result = ocr_pdf(tmp, dpi=dpi, lang=lang, max_pages=max_pages)
    finally:
        tmp.unlink(missing_ok=True)

    meta = dict(doc.meta or {})
    text = result.text
    meta["ocr"] = {
        "status": "done",
        "engine": result.engine,
        "lang": result.lang,
        "dpi": result.dpi,
        "pages_ocrd": len(result.page_texts),
        "text_chars": len(text),
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "text_preview": text[:MAX_TEXT_STORED],
        "ocrd_at": datetime.now(UTC).isoformat(),
        "candidates": {k: vars(v) for k, v in result.candidates.items()},
        "candidate_codes": {k: c.value for k, c in result.candidates.items()},
    }
    doc.meta = meta

    updates = _field_updates(doc, result.candidates)
    for key, val in updates.items():
        setattr(doc, key, val)
    if updates or result.candidates:
        origins = dict(meta.get("field_origins") or {})
        for key in (*updates, *result.candidates):
            origins.setdefault(key, MetadataOrigin.DERIVED_MACHINE.value)
        meta["field_origins"] = origins
        doc.meta = meta
        doc.metadata_origin = MetadataOrigin.DERIVED_MACHINE.value

    record_event(
        session,
        entity_type="document",
        entity_id=doc.id,
        operation=ProvenanceOp.EXTRACTED,
        input_refs=[
            {
                "entity_type": "artifact",
                "entity_id": str(artifact.id),
                "sha256": artifact.content_sha256,
            }
        ],
        tool=result.engine,
        run_id=run.id if run else None,
        parameters={
            "ocr": True,
            "lang": result.lang,
            "dpi": result.dpi,
            "pages": len(result.page_texts),
            "fields_filled": sorted(updates),
        },
    )

    pending = session.scalar(
        select(func.count(ReviewTask.id)).where(
            ReviewTask.target_type == "document",
            ReviewTask.target_id == doc.id,
            ReviewTask.task_type == TaskType.REVIEW_METADATA.value,
            ReviewTask.status == "pending",
        )
    )
    if not pending:
        session.add(
            ReviewTask(
                target_type="document",
                target_id=doc.id,
                task_type=TaskType.REVIEW_METADATA.value,
                priority=55,
                reason="OCR-derived fields — verify against the scanned original",
                evidence={
                    "ocr": {
                        "engine": result.engine,
                        "lang": result.lang,
                        "dpi": result.dpi,
                        "fields_filled": sorted(updates),
                    },
                    "candidates": {k: vars(v) for k, v in result.candidates.items()},
                },
            )
        )
    return {
        "document_id": str(doc.id),
        "pages": len(result.page_texts),
        "text_chars": len(text),
        "candidates": sorted(result.candidates),
        "fields_filled": sorted(updates),
    }


def ocr_pending_documents(
    session: Session,
    *,
    limit: int = 20,
    run: IngestionRun | None = None,
    dpi: int = DEFAULT_DPI,
    lang: str = DEFAULT_LANG,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> dict:
    """OCR a batch of scanned documents (``meta.needs_ocr``, not yet OCR'd)."""
    docs = session.scalars(
        select(Document)
        .where(Document.meta["needs_ocr"].astext == "true")
        .order_by(Document.created_at)
    ).all()
    todo = [d for d in docs if (d.meta or {}).get("ocr", {}).get("status") != "done"][
        :limit
    ]
    stats = {"processed": 0, "failed": 0, "skipped": len(docs) - len(todo), "errors": []}
    for doc in todo:
        try:
            ocr_document(session, doc, run=run, dpi=dpi, lang=lang, max_pages=max_pages)
            session.commit()  # per-doc — progress survives interruption
            stats["processed"] += 1
        except Exception as exc:  # keep batch going; artifact stays immutable
            session.rollback()
            stats["failed"] += 1
            stats["errors"].append({"document_id": str(doc.id), "error": str(exc)[:200]})
    return stats
