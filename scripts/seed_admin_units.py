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
        "reorganisation that merged Bình Dương and Bà Rịa–Vũng Tàu "
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
