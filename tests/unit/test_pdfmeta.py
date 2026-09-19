"""Unit tests for evidence-bearing PDF metadata extraction.

Uses the synthetic DemoDistrict fixture PDFs (text-bearing) plus generated
scan/blank PDFs — no network, no real documents.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openquyhoach_ingest.pdfmeta import inspect_pdf

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures" / "synthetic" / "demo_district" / "documents"


class TestTextPdf:
    def test_candidates_carry_evidence(self):
        info = inspect_pdf(FIXTURES / "qd_001_phe_duyet_v1.pdf")
        assert info.has_embedded_text
        assert not info.needs_ocr
        assert info.page_count >= 1

        # decision number extracted as a *candidate* with evidence —
        # never silently authoritative
        cand = info.candidates["decision_number"]
        assert cand.value == "001/QD-UBND-MX"
        assert cand.page is not None and cand.page >= 1
        assert cand.snippet and "001" in cand.snippet
        assert cand.pattern
        # flat map mirrors the candidate value
        assert info.candidate_codes["decision_number"] == cand.value

    def test_page_stats(self):
        info = inspect_pdf(FIXTURES / "qd_001_phe_duyet_v1.pdf")
        assert len(info.pages) == info.page_count
        assert any(p.has_text for p in info.pages)
        assert all(p.width > 0 and p.height > 0 for p in info.pages)
        assert info.text.strip()

    def test_second_fixture_extracts_its_number(self):
        info = inspect_pdf(FIXTURES / "qd_002_phe_duyet_v2.pdf")
        assert info.candidates["decision_number"].value == "002/QD-UBND-MX"


class TestScanAndBlankPdf:
    def test_image_only_pdf_needs_ocr(self, tmp_path):
        """A scan (image, no text layer) is flagged for the optional OCR path."""
        PIL = pytest.importorskip("PIL.Image")
        img = PIL.new("RGB", (64, 64), (200, 200, 200))
        p = tmp_path / "scan.pdf"
        img.save(p, "PDF")

        info = inspect_pdf(p)
        assert not info.has_embedded_text
        assert info.needs_ocr
        assert not info.candidate_codes
        assert any(pg.image_count > 0 for pg in info.pages)

    def test_blank_pdf_no_text_no_images(self, tmp_path):
        """A truly empty page has no text but also nothing to OCR."""
        from pypdf import PdfWriter

        w = PdfWriter()
        w.add_blank_page(width=200, height=200)
        p = tmp_path / "blank.pdf"
        with open(p, "wb") as fh:
            w.write(fh)

        info = inspect_pdf(p)
        assert not info.has_embedded_text
        assert not info.needs_ocr
        assert info.page_count == 1
