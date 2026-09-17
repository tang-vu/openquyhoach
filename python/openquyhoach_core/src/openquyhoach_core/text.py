"""Vietnamese-aware text normalization.

Used for search indexing and dedup. Handles full diacritic stripping
(including đ/Đ which ``unaccent`` does not fold), case and whitespace.
"""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")

# đ/Đ are standalone letters, not d + combining mark — fold them explicitly.
_SPECIAL = str.maketrans({"đ": "d", "Đ": "d"})


def vn_normalize(text: str | None) -> str:
    """Lowercase, strip diacritics, collapse whitespace. ``"Đà Nẵng" -> "da nang"``."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFD", text.translate(_SPECIAL))
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return _WS.sub(" ", stripped).strip().lower()


def fold_token(text: str | None) -> str:
    """Normalization for exact-match keys (codes): NFKC + strip + lower."""
    if not text:
        return ""
    return vn_normalize(unicodedata.normalize("NFKC", text))
