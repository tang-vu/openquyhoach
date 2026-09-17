"""Mapping between OpenQuyHoach's canonical model and the Vietnamese planning
GIS dossier structure (HoSoBASIC / HoSoScan / HoSoGIS; groups NenDiaHinh /
HienTrang / QuyHoach / MocGioi).

The canonical model is more normalized; this module only defines the
import/export *mapping* — it is data-driven, not hard-coded business logic.
Field-level mappings live in `sources/*.yaml` descriptors and can be extended
per source without code changes.
"""

from __future__ import annotations

from openquyhoach_core.enums import DatasetGroup

# dossier sections ↔ internal record linkage
HOSO_SECTIONS = {
    "HoSoBASIC": "documents/text metadata (decision, report, approval)",
    "HoSoScan": "raster artifacts (scanned maps, appendix scans)",
    "HoSoGIS": "vector datasets + layers",
}

# canonical dataset_group <-> QH layer-group names used by the VN framework
GROUP_MAPPING = {
    DatasetGroup.NEN_DIA_HINH: ["NenDiaHinh", "nen_dia_hinh", "terrain"],
    DatasetGroup.HIEN_TRANG: ["HienTrang", "hien_trang", "existing"],
    DatasetGroup.QUY_HOACH: ["QuyHoach", "quy_hoach", "planning"],
    DatasetGroup.MOC_GIOI: ["MocGioi", "moc_gioi", "boundary_markers"],
    DatasetGroup.HOSO_GIS: ["HoSoGIS"],
}


def normalize_group_name(raw: str | None) -> str:
    """Map a source layer-group name to a canonical dataset_group."""
    if not raw:
        return DatasetGroup.HOSO_GIS.value
    low = raw.strip().lower().replace(" ", "").replace("-", "_")
    for group, aliases in GROUP_MAPPING.items():
        if low in {a.lower().replace("-", "_") for a in aliases}:
            return group.value
    return DatasetGroup.OTHER.value
