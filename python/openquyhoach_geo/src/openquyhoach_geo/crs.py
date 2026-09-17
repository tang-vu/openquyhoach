"""CRS handling policy.

Rules that protect correctness:

* Never guess a CRS — especially never "assume VN-2000" for a bare pair of
  projected coordinates. If the CRS cannot be identified reliably the data is
  flagged ``QH-CRS-MISSING`` and geometry is stored untransformed.
* Preserve the source CRS description verbatim (EPSG code when present, plus
  WKT / PROJJSON / the raw driver string).
* Canonical API/web geometry is EPSG:4326 lon/lat; Web Mercator is only a
  *rendering* CRS and never stored as data.
* Every reprojection is recorded as a provenance event with the exact CRS
  identifiers used, so it is reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from openquyhoach_core.errors import CRSError
from pyproj import CRS

CANONICAL_SRID = 4326
WEB_MERCATOR_SRID = 3857

# VN-2000 detection. The EPSG registry spreads VN-2000 realisations across
# several blocks (geographic 4756; UTM 48N/49N = 3405/3406; TM-3 zones at e.g.
# 5896, 6956-6959, 9210-9222). Rather than enumerate every code we check the
# *base geodetic CRS*: any projected CRS built on EPSG:4756 is VN-2000.
VN2000_BASE_EPSG = 4756
VN2000_UTM_EPSGS = {3405, 3406}


@dataclass
class CRSInfo:
    """Everything we know about a dataset's CRS, verbatim."""

    srid: int | None = None
    epsg: int | None = None
    wkt: str | None = None
    projjson: dict | None = None
    raw: str | None = None  # driver-reported string when not parseable
    identified: bool = False
    is_vn2000: bool = False
    name: str | None = None
    axis_order: str | None = None  # "ne" | "en" | None
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "srid": self.srid,
            "epsg": self.epsg,
            "wkt": self.wkt,
            "projjson": self.projjson,
            "raw": self.raw,
            "identified": self.identified,
            "is_vn2000": self.is_vn2000,
            "name": self.name,
            "axis_order": self.axis_order,
            "warnings": self.warnings,
        }


def describe_crs(crs: CRS | str | int | None, raw: str | None = None) -> CRSInfo:
    """Build a CRSInfo from whatever the driver gave us. Never raises —
    unidentified CRS is a first-class, flagged state."""
    info = CRSInfo(raw=raw)
    if crs is None:
        info.warnings.append("no_crs_reported")
        return info
    try:
        obj = crs if isinstance(crs, CRS) else CRS.from_user_input(crs)
    except Exception:
        info.warnings.append("unparseable_crs")
        return info
    info.identified = True
    info.name = obj.name
    info.wkt = obj.to_wkt()
    try:
        info.projjson = obj.to_json_dict()
    except Exception:
        info.projjson = None
    epsg = obj.to_epsg()
    info.epsg = epsg
    info.srid = epsg
    if obj.axis_info:
        first = str(obj.axis_info[0].abbrev).lower()
        info.axis_order = "ne" if first in {"n", "lat"} else "en"
    info.is_vn2000 = _is_vn2000(obj)
    if epsg is None:
        info.warnings.append("no_epsg_code")  # stored via WKT/PROJJSON instead
    return info


def _is_vn2000(crs: CRS) -> bool:
    """True when the CRS realises the VN-2000 datum (base geodetic EPSG:4756)
    or identifies itself by name."""
    try:
        base = crs.geodetic_crs
        if base is not None and base.to_epsg() == VN2000_BASE_EPSG:
            return True
    except Exception:
        pass
    if crs.to_epsg() in (VN2000_BASE_EPSG, *VN2000_UTM_EPSGS):
        return True
    return "vn-2000" in crs.name.lower() or "vn2000" in crs.name.lower()


def require_identified(info: CRSInfo) -> CRS:
    """Gatekeeper: transform only when the source CRS is reliably identified."""
    if not info.identified:
        raise CRSError(
            "CRS is not reliably identified — refusing to guess a transformation",
            detail={"crs": info.to_json()},
        )
    return CRS.from_wkt(info.wkt) if info.wkt else CRS.from_user_input(info.raw)  # type: ignore[arg-type]


def canonical_transformer(info: CRSInfo):
    """Transformer source->EPSG:4326, honouring source axis order."""
    from pyproj import Transformer

    src = require_identified(info)
    return Transformer.from_crs(src, CRS.from_epsg(CANONICAL_SRID), always_xy=True)


def looks_like_degrees(x: float, y: float) -> bool:
    """Sanity check: plausible lon/lat for Vietnam's extent (generous bounds)."""
    return 100.0 <= x <= 117.0 and 5.0 <= y <= 26.0
