"""PDF inspection — metadata first, embedded text second, OCR never here.

Order per spec §11: inspect metadata → extract embedded text → inspect
embedded images/vectors → OCR is an explicit optional stage (AI providers),
never automatic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PdfPageInfo:
    page: int
    width: float
    height: float
    text_chars: int
    has_text: bool
    image_count: int


@dataclass
class PdfInfo:
    page_count: int
    metadata: dict
    pages: list[PdfPageInfo] = field(default_factory=list)
    text: str = ""  # concatenated embedded text (capped)
    has_embedded_text: bool = False
    needs_ocr: bool = False
    candidate_codes: dict = field(default_factory=dict)  # parsed *candidates* only


# VN legal-document hints — patterns that *suggest* metadata. Anything found
# stays a candidate requiring evidence/review; never authoritative.
# Patterns are written against diacritics-folded text (see ``vn_normalize``)
# because scanned/OCR'd Vietnamese documents routinely lose diacritics.
RE_DECISION = re.compile(
    r"(?:quyet dinh|qd|decision)\s*(?:so|no\.?|number)?\s*[:\-]?\s*([0-9]{1,6}/[^\s,;]+)", re.I
)
RE_DATE = re.compile(r"ngay\s+(\d{1,2})\s+thang\s+(\d{1,2})\s+nam\s+(\d{4})", re.I)
RE_MA_QH = re.compile(
    r"(?:ma\s+(?:thong tin\s+)?quy hoach|ma\s+qh)\s*[:\-]?\s*([a-z0-9\-\.]+)", re.I
)
RE_SCALE = re.compile(r"(?:ty\s*le|scale)\s*[:\-]?\s*(1\s*[/:]\s*\d{3,6})", re.I)

MAX_TEXT_CHARS = 200_000


def inspect_pdf(path: str | Path) -> PdfInfo:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    meta = {k.lstrip("/"): str(v) for k, v in (reader.metadata or {}).items()}
    pages: list[PdfPageInfo] = []
    text_parts: list[str] = []
    total_text = 0
    for i, page in enumerate(reader.pages):
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        try:
            images = len(page.images)
        except Exception:
            images = 0
        box = page.mediabox
        pages.append(
            PdfPageInfo(
                page=i + 1,
                width=float(box.width),
                height=float(box.height),
                text_chars=len(txt),
                has_text=bool(txt.strip()),
                image_count=images,
            )
        )
        if total_text < MAX_TEXT_CHARS:
            text_parts.append(txt)
            total_text += len(txt)
    text = "\n".join(text_parts)
    has_text = any(p.has_text for p in pages)

    from openquyhoach_core.text import vn_normalize

    folded = vn_normalize(text)  # diacritics-insensitive candidate scan
    candidates: dict[str, str] = {}
    m = RE_DECISION.search(folded)
    if m:
        candidates["decision_number"] = m.group(1).strip().upper()
    m = RE_DATE.search(folded)
    if m:
        d, mo, y = m.groups()
        candidates["signed_date"] = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    m = RE_MA_QH.search(folded)
    if m:
        candidates["planning_code"] = m.group(1).strip().upper()
    m = RE_SCALE.search(folded)
    if m:
        candidates["scale"] = m.group(1).replace(" ", "")

    return PdfInfo(
        page_count=len(reader.pages),
        metadata=meta,
        pages=pages,
        text=text,
        has_embedded_text=has_text,
        needs_ocr=not has_text and any(p.image_count > 0 for p in pages),
        candidate_codes=candidates,
    )
