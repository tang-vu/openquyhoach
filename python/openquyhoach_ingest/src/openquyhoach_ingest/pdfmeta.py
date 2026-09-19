"""PDF inspection — metadata first, embedded text second, OCR never here.

Order per spec §11: inspect metadata → extract embedded text → inspect
embedded images/vectors → OCR is an explicit optional stage (AI providers),
never automatic.

Every extracted candidate carries its evidence (page + snippet + pattern)
so reviewers can verify, and so the pipeline can tag fields with the right
``metadata_origin`` — machine extraction is never silently official.
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
class Candidate:
    """A regex-derived metadata candidate with its evidence."""

    value: str
    page: int | None = None
    snippet: str | None = None
    pattern: str | None = None


@dataclass
class PdfInfo:
    page_count: int
    metadata: dict
    pages: list[PdfPageInfo] = field(default_factory=list)
    text: str = ""  # concatenated embedded text (capped)
    has_embedded_text: bool = False
    needs_ocr: bool = False
    candidate_codes: dict = field(default_factory=dict)  # parsed *candidates* only
    candidates: dict[str, Candidate] = field(default_factory=dict)  # with evidence


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
# "co hieu luc tu ngay dd/mm/yyyy" / "co hieu luc ke tu ngay ky"
RE_EFFECTIVE = re.compile(
    r"co\s+hieu\s+luc(?:\s+thi\s+hanh)?\s+(?:tu\s+)?ngay\s+(\d{1,2})[\-/](\d{1,2})[\-/](\d{4})", re.I
)
RE_EFFECTIVE_SIGNED = re.compile(
    r"co\s+hieu\s+luc(?:\s+thi\s+hanh)?\s+ke\s+tu\s+ngay\s+ky", re.I
)
# issuing authority in the masthead, e.g. "UY BAN NHAN DAN TINH/THANH PHO X"
RE_AUTHORITY = re.compile(
    r"(uy\s+ban\s+nhan\s+dan|bo\s+[a-z]+|so\s+[a-z\s]+?)\s+(tinh|thanh\s+pho|huyen|quan|thi\s+xa|phuong|xa)\s+([a-z\s]+)",
    re.I,
)
# "thay the quyet dinh so NNN/..." — superseded decision reference
RE_SUPERSEDES = re.compile(
    r"thay\s+the\s+(?:quyet\s+dinh|qd)\s*(?:so)?\s*[:\-]?\s*([0-9]{1,6}/[^\s,;]+)", re.I
)
# "quy hoach chung / quy hoach phan khu / quy hoach chi tiet ..." title hint
RE_PLAN_TITLE = re.compile(
    r"(quy\s+hoach\s+(?:chung|phan\s+khu|chi\s+tiet|xay\s+dung|su\s+dung\s+dat|nganh)[^\.\n]{0,120})",
    re.I,
)
RE_PLANNING_PERIOD = re.compile(
    r"(?:thoi\s+ky|giai\s+doan)\s+(?:quy\s+hoach\s+)?(?:den\s+nam|den)?\s*(\d{4})\s*(?:[-–]|den\s+nam)?\s*(\d{4})?",  # noqa: RUF001 - en-dash intentional: VN docs write ranges like 2021-2030 with it
    re.I,
)

MAX_TEXT_CHARS = 200_000


def _snippet(folded_page: str, match: re.Match, span: int = 90) -> str:
    start = max(0, match.start() - 20)
    return folded_page[start : match.end() + span].strip()[:160]


def inspect_pdf(path: str | Path) -> PdfInfo:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    meta = {k.lstrip("/"): str(v) for k, v in (reader.metadata or {}).items()}
    pages: list[PdfPageInfo] = []
    page_texts: list[str] = []
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
            page_texts.append(txt)
            total_text += len(txt)
    text = "\n".join(page_texts)
    has_text = any(p.has_text for p in pages)

    from openquyhoach_core.text import vn_normalize

    folded_pages = [vn_normalize(t) for t in page_texts]

    def _first(name: str, pattern: re.Pattern, group_fmt) -> None:
        """Record the first match with page + snippet evidence."""
        for pageno, fp in enumerate(folded_pages, start=1):
            m = pattern.search(fp)
            if m:
                candidates[name] = Candidate(
                    value=group_fmt(m),
                    page=pageno,
                    snippet=_snippet(fp, m),
                    pattern=pattern.pattern[:120],
                )
                return

    candidates: dict[str, Candidate] = {}
    _first("decision_number", RE_DECISION, lambda m: m.group(1).strip().upper())
    _first(
        "signed_date",
        RE_DATE,
        lambda m: f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}",
    )
    _first("planning_code", RE_MA_QH, lambda m: m.group(1).strip().upper())
    _first("scale", RE_SCALE, lambda m: m.group(1).replace(" ", ""))
    _first(
        "effective_date",
        RE_EFFECTIVE,
        lambda m: f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}",
    )
    _first("effective_from_signed", RE_EFFECTIVE_SIGNED, lambda m: "signed_date")
    _first(
        "approving_authority",
        RE_AUTHORITY,
        lambda m: " ".join(m.group(0).split()),
    )
    _first("supersedes_decision", RE_SUPERSEDES, lambda m: m.group(1).strip().upper())
    _first("plan_title", RE_PLAN_TITLE, lambda m: " ".join(m.group(1).split()))
    _first(
        "planning_period",
        RE_PLANNING_PERIOD,
        lambda m: "-".join(g for g in m.groups() if g),
    )

    # flat value map kept for existing consumers
    candidate_codes = {k: c.value for k, c in candidates.items()}

    return PdfInfo(
        page_count=len(reader.pages),
        metadata=meta,
        pages=pages,
        text=text,
        has_embedded_text=has_text,
        needs_ocr=not has_text and any(p.image_count > 0 for p in pages),
        candidate_codes=candidate_codes,
        candidates=candidates,
    )
