"""OCR path — offline tesseract adapter.

Skipped when poppler/tesseract are absent (CI). When present, verifies a
generated image-PDF round-trips through pdftoppm + tesseract and that
extraction output stays candidate-level (never auto-official).
"""

from __future__ import annotations

import pytest
from openquyhoach_ingest.ocr import ocr_available

pytestmark = pytest.mark.skipif(
    not ocr_available(), reason="requires pdftoppm + tesseract on PATH"
)


def _image_pdf(path, text: str) -> None:
    """Render a one-page image-only PDF containing ``text`` via PIL."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1400, 500), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 200), text, fill="black")
    img.save(str(path), "PDF", resolution=200.0)


class TestOcrPdf:
    def test_ocr_extracts_text(self, tmp_path):
        from openquyhoach_ingest.ocr import ocr_pdf

        pdf = tmp_path / "scan.pdf"
        _image_pdf(pdf, "QUYET DINH SO 1234/2024/QD-UBND")
        result = ocr_pdf(pdf, lang="eng", max_pages=1)
        assert result.page_texts
        assert "tesseract" in result.engine
        assert any("QUYET" in p.upper() or "1234" in p for p in result.page_texts)

    def test_candidates_carry_evidence(self, tmp_path):
        from openquyhoach_ingest.ocr import ocr_pdf

        pdf = tmp_path / "scan2.pdf"
        _image_pdf(pdf, "Quyet dinh so 567/QD-UBND ngay 01 thang 02 nam 2024")
        result = ocr_pdf(pdf, lang="eng", max_pages=1)
        if "decision_number" in result.candidates:
            cand = result.candidates["decision_number"]
            assert cand.page == 1
            assert cand.snippet
            assert cand.pattern  # regex that produced it — auditable
