"""Vietnamese text normalisation — diacritics-insensitive matching."""

from __future__ import annotations

from openquyhoach_core.text import vn_normalize


def test_diacritics_folded():
    assert vn_normalize("Đất ở đô thị") == vn_normalize("dat o do thi")
    assert vn_normalize("Quy hoạch") == "quy hoach"
    assert vn_normalize("Hà Nội") == vn_normalize("ha noi")


def test_case_and_space():
    assert vn_normalize("  NINH   BÌNH ") == "ninh binh"
    assert vn_normalize("") == ""


def test_d_stroke():
    # đ/Đ is not a combining-mark letter — must be mapped explicitly
    assert vn_normalize("Đồng") == "dong"
