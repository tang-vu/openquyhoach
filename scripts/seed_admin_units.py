"""Seed real administrative units needed by pilot sources.

Only units with verified GSO (General Statistics Office) mã đơn vị hành
chính are seeded — never guessed codes, never invented boundaries.
Rows carry `source`/`meta.notes` documenting the reference basis.

    uv run python scripts/seed_admin_units.py
"""

from __future__ import annotations

from datetime import date

from openquyhoach_core.db import session_scope
from openquyhoach_core.models import AdministrativeUnit
from openquyhoach_core.text import vn_normalize

# (official_code, name, level, valid_from, valid_to, note)
UNITS = [
    (
        "79",
        "Thành phố Hồ Chí Minh",
        "province",
        None,
        None,
        "GSO mã tỉnh 79 — stable through the 2025 administrative "
        "reorganisation that merged Bình Dương and Bà Rịa-Vũng Tàu "
        "into the expanded city (effective 2025-07-01).",
    ),
    (
        "769",
        "Thành phố Thủ Đức",
        "district",
        date(2021, 1, 1),
        date(2025, 6, 30),
        "GSO mã 769 — municipal city established by NQ 1111/NQ-UBTVQH14 "
        "(effective 2021-01-01); ceased as a district-level unit in the "
        "2025 reorganisation of Thành phố Hồ Chí Minh.",
    ),
    (
        "01",
        "Thành phố Hà Nội",
        "province",
        None,
        None,
        "GSO mã tỉnh 01 — stable through the 2025 administrative "
        "reorganisation (commune-level consolidation effective "
        "2025-07-01 did not change the province-level unit).",
    ),
    (
        "56",
        "Tỉnh Khánh Hòa",
        "province",
        None,
        date(2025, 6, 30),
        "GSO mã tỉnh 56 — merged with Ninh Thuận in the 2025 "
        "reorganisation (new Khánh Hòa province effective 2025-07-01); "
        "this row is the pre-merge unit referenced by current layers.",
    ),
    (
        "31",
        "Thành phố Hải Phòng",
        "province",
        None,
        None,
        "GSO mã tỉnh 31 — post-2025 expanded city (merged Hải Dương).",
    ),
    (
        "92",
        "Thành phố Cần Thơ",
        "province",
        None,
        None,
        "GSO mã tỉnh 92 — post-2025 expanded city (merged Sóc Trăng, "
        "Hậu Giang).",
    ),
    (
        "72",
        "Tỉnh Tây Ninh",
        "province",
        None,
        date(2025, 6, 30),
        "GSO mã tỉnh 72 — merged with Long An in the 2025 "
        "reorganisation (new Tây Ninh province effective 2025-07-01); "
        "this row is the pre-merge unit referenced by current layers.",
    ),
    (
        "89",
        "Tỉnh An Giang",
        "province",
        None,
        None,
        "Mã cấp 1 theo QĐ 09/2025/QĐ-TTg — tỉnh An Giang mới "
        "(sáp nhập Kiên Giang, hiệu lực 2025-07-01) giữ mã 89 của "
        "tỉnh trùng tên; mã 91 của Kiên Giang đóng.",
    ),
    (
        "37",
        "Tỉnh Ninh Bình",
        "province",
        date(2025, 7, 1),
        None,
        "QĐ 19/2025/QĐ-TTg + NQ 202/2025/QH15 — tỉnh Ninh Bình mới "
        "(sáp nhập Hà Nam 35, Nam Định 36, Ninh Bình 37; hiệu lực "
        "2025-07-01) giữ mã 37 của tỉnh trùng tên.",
    ),
    (
        "37",
        "Tỉnh Ninh Bình",
        "province",
        None,
        date(2025, 6, 30),
        "GSO mã tỉnh 37 — đơn vị tiền sáp nhập; QH tỉnh cũ "
        "(218/QĐ-TTg) vẫn tham chiếu đơn vị này.",
    ),
    (
        "35",
        "Tỉnh Hà Nam",
        "province",
        None,
        date(2025, 6, 30),
        "GSO mã tỉnh 35 — đóng sau sáp nhập vào tỉnh Ninh Bình mới "
        "(NQ 202/2025/QH15); QH tỉnh Hà Nam (1686/QĐ-TTg, tầm nhìn "
        "2050) vẫn là văn bản hiệu lực cho lãnh thổ cũ.",
    ),
    (
        "36",
        "Tỉnh Nam Định",
        "province",
        None,
        date(2025, 6, 30),
        "GSO mã tỉnh 36 — đóng sau sáp nhập vào tỉnh Ninh Bình mới "
        "(NQ 202/2025/QH15); QH tỉnh Nam Định (1729/QĐ-TTg) tham "
        "chiếu đơn vị này.",
    ),
]


def main() -> None:
    with session_scope() as s:
        parent = None
        for code, name, level, vf, vt, note in UNITS:
            unit = (
                s.query(AdministrativeUnit)
                .filter_by(official_code=code, valid_to=vt)
                .one_or_none()
            )
            if unit is None:
                unit = AdministrativeUnit(
                    official_code=code,
                    name=name,
                    normalized_name=vn_normalize(name),
                    level=level,
                    parent_id=parent.id if parent and level == "district" else None,
                    valid_from=vf,
                    valid_to=vt,
                    source="GSO mã đơn vị hành chính (manual seed)",
                    meta={"notes": note, "seeded": True},
                )
                s.add(unit)
                s.flush()
                print(f"seeded {code} {name} ({level})")
            else:
                print(f"exists  {code} {name} ({level})")
            if level == "province":
                parent = unit


if __name__ == "__main__":
    main()
