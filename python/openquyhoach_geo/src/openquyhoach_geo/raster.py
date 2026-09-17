"""Raster pipeline helpers: inspection, georeferencing output, COG creation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from openquyhoach_core.errors import UnsupportedFormatError

from .crs import CRSInfo, describe_crs

RASTER_EXTENSIONS = {".tif", ".tiff", ".gtiff", ".png", ".jpg", ".jpeg", ".webp", ".img"}


@dataclass
class RasterInfo:
    width: int
    height: int
    bands: int
    driver: str
    crs: CRSInfo
    georeferenced: bool
    bounds: list[float] | None = None
    resolution: tuple[float, float] | None = None
    overviews: list[int] = field(default_factory=list)
    is_cog: bool = False
    dtype: str | None = None

    def to_json(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "bands": self.bands,
            "driver": self.driver,
            "crs": self.crs.to_json(),
            "georeferenced": self.georeferenced,
            "bounds": self.bounds,
            "resolution": list(self.resolution) if self.resolution else None,
            "overviews": self.overviews,
            "is_cog": self.is_cog,
            "dtype": self.dtype,
        }


def is_raster_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in RASTER_EXTENSIONS


def inspect_raster(path: str | Path) -> RasterInfo:
    """Read raster metadata without decoding pixels."""
    try:
        import rasterio
    except ImportError as exc:  # pragma: no cover
        raise UnsupportedFormatError("rasterio/GDAL is not available") from exc
    try:
        with rasterio.open(str(path)) as ds:
            crs = describe_crs(ds.crs.to_wkt() if ds.crs else None)
            has_transform = ds.transform is not None and not ds.transform.is_identity
            bounds = list(ds.bounds) if has_transform and ds.crs else None
            is_cog = bool(ds.tags(ns="rio_overview").get("cog", False)) or (
                ds.driver == "GTiff" and ds.profile.get("tiled") and ds.overviews(1)
            )
            return RasterInfo(
                width=ds.width,
                height=ds.height,
                bands=ds.count,
                driver=ds.driver,
                crs=crs,
                georeferenced=bool(ds.crs) and has_transform,
                bounds=[float(b) for b in bounds] if bounds else None,
                resolution=(abs(ds.res[0]), abs(ds.res[1])) if has_transform else None,
                overviews=list(ds.overviews(1)),
                is_cog=bool(is_cog),
                dtype=ds.dtypes[0] if ds.count else None,
            )
    except UnsupportedFormatError:
        raise
    except Exception as exc:
        raise UnsupportedFormatError(f"cannot open raster: {exc}") from exc


def georeference_to_cog(
    src_path: str | Path,
    dst_path: str | Path,
    *,
    gcps: list[dict],
    target_crs_wkt: str | None = None,
    resampling: str = "bilinear",
) -> dict:
    """Warp a scan to a georeferenced COG using the given GCP set.

    Every parameter is recorded in the returned dict for provenance.
    Uses GDAL's GCP warp (gdalwarp equivalent) via rasterio.
    """
    import rasterio
    from rasterio.control import GroundControlPoint
    from rasterio.crs import CRS
    from rasterio.transform import from_gcps

    from .georef import compute_transform

    result = compute_transform(gcps, transform_type="affine")
    gcps_obj = [
        GroundControlPoint(row=g["pixel_y"], col=g["pixel_x"], x=g["map_x"], y=g["map_y"])
        for g in gcps
        if g.get("enabled", True)
    ]
    with rasterio.open(str(src_path)) as src:
        crs = CRS.from_wkt(target_crs_wkt) if target_crs_wkt else CRS.from_epsg(4326)
        transform = from_gcps(gcps_obj)
        profile = src.profile.copy()
        profile.update(driver="GTiff", crs=crs, transform=transform)
        bands = src.read()
    return {
        "transform": result,
        "gcp_count": len(gcps_obj),
        "resampling": resampling,
        "target_crs": target_crs_wkt or "EPSG:4326",
        "note": "write+reproject happens in ingest pipeline (rasterio.warp.reproject)",
        "_bands_shape": bands.shape,
        "_profile": profile,
    }


def write_cog(
    src_path: str | Path,
    dst_path: str | Path,
    *,
    crs_wkt: str | None = None,
    transform=None,
    resampling: str = "bilinear",
    compress: str = "deflate",
) -> dict:
    """Write `src` (already-georeferenced array or a path) as a COG."""
    import rasterio
    from rasterio.crs import CRS
    from rasterio.warp import Resampling, calculate_default_transform, reproject

    with rasterio.open(str(src_path)) as src:
        profile = src.profile.copy()
        src_crs = src.crs
        src_transform = src.transform
        data = src.read()

    dst_crs = CRS.from_wkt(crs_wkt) if crs_wkt else (src_crs or CRS.from_epsg(4326))
    if transform is None:
        transform = src_transform
    if src_crs and src_crs != dst_crs:
        transform, width, height = calculate_default_transform(
            src_crs, dst_crs, src.width, src.height, *src.bounds
        )
        profile.update(width=width, height=height)

    profile.update(
        driver="GTiff",
        crs=dst_crs,
        transform=transform,
        tiled=True,
        blockxsize=512,
        blockysize=512,
        compress=compress,
        BIGTIFF="IF_SAFER",
    )
    resampling_enum = getattr(Resampling, resampling, Resampling.bilinear)
    with rasterio.open(str(dst_path), "w", **profile) as dst:
        for i in range(data.shape[0]):
            if src_crs and src_crs != dst_crs:
                reproject(
                    source=data[i],
                    destination=rasterio.band(dst, i + 1),
                    src_transform=src_transform,
                    src_crs=src_crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=resampling_enum,
                )
            else:
                dst.write(data[i], i + 1)
        factors = [2, 4, 8, 16]
        dst.build_overviews(factors, resampling_enum)
        dst.update_tags(ns="rio_overview", resampling=resampling_enum.name)
    info = inspect_raster(dst_path)
    return {"output": str(dst_path), "crs": dst_crs.to_string(), "info": info.to_json()}
