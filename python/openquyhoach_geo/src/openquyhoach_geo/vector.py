"""Vector file inspection and reading via GDAL (pyogrio).

Supports everything the local GDAL build supports — GeoPackage, GeoJSON,
Shapefile, KML, DXF, FileGDB (read-only driver dependent). DWG is detected
but never decoded (no bundled proprietary codecs — see docs/compliance).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openquyhoach_core.errors import UnsupportedFormatError
from shapely.geometry.base import BaseGeometry

from .crs import CRSInfo, describe_crs

VECTOR_EXTENSIONS = {
    ".gpkg",
    ".geojson",
    ".json",
    ".shp",
    ".kml",
    ".dxf",
    ".fgb",
    ".sqlite",
    ".gdb",
}
DWG_EXTENSIONS = {".dwg"}


@dataclass
class VectorLayerInfo:
    name: str
    geometry_type: str | None
    feature_count: int
    crs: CRSInfo
    fields: list[dict[str, str]] = field(default_factory=list)


@dataclass
class VectorFeature:
    geometry: BaseGeometry | None
    properties: dict[str, Any]
    fid: int | None = None


def _require_pyogrio():
    try:
        import pyogrio
    except ImportError as exc:  # pragma: no cover
        raise UnsupportedFormatError("pyogrio/GDAL is not available in this environment") from exc
    return pyogrio


def is_vector_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in VECTOR_EXTENSIONS


def is_dwg(path: str | Path) -> bool:
    return Path(path).suffix.lower() in DWG_EXTENSIONS


def _clean_value(val: Any) -> Any:
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    if hasattr(val, "item"):
        return val.item()
    return val


def list_layers(path: str | Path) -> list[VectorLayerInfo]:
    """Inspect layers of a vector container without loading features."""
    if is_dwg(path):
        raise UnsupportedFormatError(
            "DWG requires conversion to DXF/GeoPackage with a licensed tool; "
            "OpenQuyHoach does not bundle proprietary DWG codecs."
        )
    pyogrio = _require_pyogrio()
    path = str(path)
    try:
        layers = pyogrio.list_layers(path)
    except Exception as exc:
        raise UnsupportedFormatError(f"cannot open vector file: {exc}") from exc
    out = []
    for row in layers:
        name = row[0]
        try:
            info = pyogrio.read_info(path, layer=name)
        except Exception as exc:
            raise UnsupportedFormatError(f"cannot inspect layer {name!r}: {exc}") from exc
        crs_raw = info.get("crs") or None

        # pyogrio returns parallel ndarrays: fields (names) + dtypes + ogr_types
        def _arr(key, _info=info):
            v = _info.get(key)
            return [str(x) for x in v] if v is not None else []

        names = _arr("fields")
        dtypes = _arr("dtypes")
        ogr_types = _arr("ogr_types")
        fields = [
            {
                "name": n,
                "dtype": dtypes[i] if i < len(dtypes) else None,
                "ogr_type": ogr_types[i] if i < len(ogr_types) else None,
            }
            for i, n in enumerate(names)
        ]
        out.append(
            VectorLayerInfo(
                name=name,
                geometry_type=info.get("geometry_type"),
                feature_count=int(info.get("features", 0)),
                crs=describe_crs(crs_raw, raw=crs_raw),
                fields=fields,
            )
        )
    return out


def layer_crs(path: str | Path, layer: str | None = None) -> CRSInfo:
    pyogrio = _require_pyogrio()
    info = pyogrio.read_info(str(path), layer=layer) if layer else pyogrio.read_info(str(path))
    raw = info.get("crs") or None
    return describe_crs(raw, raw=raw)


def iter_features(
    path: str | Path,
    layer: str | None = None,
    *,
    max_features: int | None = None,
) -> Iterator[VectorFeature]:
    """Stream features; preserves source properties verbatim."""
    import shapely

    pyogrio = _require_pyogrio()
    meta, index, geometries, field_data = pyogrio.raw.read(
        str(path), layer=layer, return_fids=True, max_features=max_features
    )
    # meta["fields"] is a plain ndarray of names (not a structured dtype)
    field_names = [str(n) for n in (meta.get("fields") if meta.get("fields") is not None else [])]
    fid_column = meta.get("fid_column")
    for i in range(len(geometries)):
        props: dict[str, Any] = {}
        for j, fname in enumerate(field_names):
            props[str(fname)] = _clean_value(field_data[j][i])
        geom = shapely.from_wkb(geometries[i]) if geometries[i] is not None else None
        fid = None
        if fid_column and fid_column in props:
            try:
                fid = int(props[fid_column])
            except (TypeError, ValueError):
                fid = None
        elif index is not None and len(index) > i:
            try:
                fid = int(index[i])
            except (TypeError, ValueError):
                fid = None
        yield VectorFeature(geometry=geom, properties=props, fid=fid)


def read_layer(path: str | Path, layer: str | None = None) -> tuple[list[VectorFeature], CRSInfo]:
    return list(iter_features(path, layer)), layer_crs(path, layer)


def geojson_to_features(payload: bytes | str) -> tuple[list[VectorFeature], CRSInfo]:
    """Parse GeoJSON in memory (fixture/test path)."""
    import shapely.geometry

    data = json.loads(payload)
    feats: list[VectorFeature] = []
    if data.get("type") == "FeatureCollection":
        for f in data.get("features", []):
            geom = shapely.geometry.shape(f["geometry"]) if f.get("geometry") else None
            feats.append(
                VectorFeature(
                    geometry=geom,
                    properties=f.get("properties") or {},
                    fid=f.get("id") if isinstance(f.get("id"), int) else None,
                )
            )
    return feats, describe_crs(4326)  # GeoJSON is WGS84 per RFC 7946
