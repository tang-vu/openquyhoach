"""Generate deterministic synthetic fixtures under fixtures/.

Everything here is INVENTED data for the fictional "Tỉnh Mẫu / DemoDistrict".
It exists to exercise the pipeline end-to-end without touching real sources.
Run: .venv/bin/python scripts/generate_fixtures.py
"""

from __future__ import annotations

import io
import struct
import zlib
from pathlib import Path

import numpy as np
import rasterio
import shapely
from pyogrio.raw import write as gpkg_write
from rasterio.transform import from_origin
from shapely.geometry import LineString, Polygon, box

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "synthetic" / "demo_district"

# DemoDistrict footprint, invented coordinates near lon 105.90 lat 20.95.
# ~4 km x 4 km.
LON0, LAT0 = 105.88, 20.93
DEG = 0.0375  # ~4km

SYNTHETIC_NOTE = "SYNTHETIC FIXTURE — invented planning data, no legal meaning"


def _poly(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return box(LON0 + x0 * DEG, LAT0 + y0 * DEG, LON0 + x1 * DEG, LAT0 + y1 * DEG)


def write_gpkg(
    path: Path,
    layer_name: str,
    geoms: list,
    field_data: dict,
    fields: list[tuple[str, str]],
    geometry_type: str,
):
    names = np.array([f[0] for f in fields], dtype="object")
    columns = [field_data[n] for n in names]
    wkb = np.array([shapely.to_wkb(g) for g in geoms], dtype="object")
    gpkg_write(
        str(path),
        wkb,
        columns,
        fields=names,
        geometry_type=geometry_type,
        driver="GPKG",
        layer=layer_name,
        crs="EPSG:4326",
    )


def land_use_v1() -> tuple[list, dict]:
    geoms = [
        _poly(0.05, 0.55, 0.45, 0.95),
        _poly(0.55, 0.55, 0.95, 0.95),
        _poly(0.05, 0.05, 0.45, 0.45),
        _poly(0.55, 0.05, 0.95, 0.45),
    ]
    field_data = {
        "ma_loai_dat": np.array(["ODT", "DVCL", "CAY", "CN"], dtype="object"),
        "ten_loai_dat": np.array(
            ["Đất ở đô thị", "Đất cây xanh", "Đất công viên", "Đất công nghiệp"], dtype="object"
        ),
        "dien_tich_ha": np.array([14.6, 14.6, 14.6, 14.6]),
        "synthetic": np.array([1, 1, 1, 1]),
    }
    return geoms, field_data


def land_use_v2() -> tuple[list, dict]:
    """v2: ODT shrinks (right half becomes TT commercial), CAY grows."""
    geoms = [
        _poly(0.05, 0.55, 0.35, 0.95),
        _poly(0.35, 0.55, 0.45, 0.95),
        _poly(0.55, 0.55, 0.95, 0.95),
        _poly(0.05, 0.05, 0.50, 0.45),
        _poly(0.50, 0.05, 0.95, 0.45),
    ]
    field_data = {
        "ma_loai_dat": np.array(["ODT", "TT", "DVCL", "CAY", "CN"], dtype="object"),
        "ten_loai_dat": np.array(
            [
                "Đất ở đô thị",
                "Đất thương mại dịch vụ",
                "Đất cây xanh",
                "Đất công viên",
                "Đất công nghiệp",
            ],
            dtype="object",
        ),
        "dien_tich_ha": np.array([10.95, 3.65, 14.6, 16.425, 16.425]),
        "synthetic": np.array([1, 1, 1, 1, 1]),
    }
    return geoms, field_data


def transport(version: int) -> tuple[list, dict]:
    def line(pts):
        return LineString([(LON0 + x * DEG, LAT0 + y * DEG) for x, y in pts])

    geoms = [
        line([(0, 0.5), (1.0, 0.5)]),  # east-west main road
        line([(0.5, 0), (0.5, 1.0)]),  # north-south main road
    ]
    if version == 2:
        geoms.append(line([(0.5, 0.5), (0.95, 0.95)]))  # new diagonal link
    n = len(geoms)
    field_data = {
        "ma_tuyen": np.array([f"TL-{i + 1:02d}" for i in range(n)], dtype="object"),
        "cap_duong": np.array(
            ["chính"] * (n - 1) + (["mới"] if version == 2 else ["chính"]), dtype="object"
        ),
        "do_rong_m": np.array([24.0] * n),
        "synthetic": np.array([1] * n),
    }
    return geoms, field_data


def boundary() -> tuple[list, dict]:
    geoms = [_poly(0, 0, 1, 1)]
    field_data = {
        "ten_don_vi": np.array(["DemoDistrict (SYNTHETIC)"], dtype="object"),
        "cap": np.array(["huyện"], dtype="object"),
        "synthetic": np.array([1]),
    }
    return geoms, field_data


def make_pdf(path: Path, title: str, decision_no: str, day: int, month: int, year: int):
    """Hand-build a minimal but valid single-page PDF with extractable ASCII text."""
    lines = [
        ("UBND TINH MAU (SYNTHETIC FIXTURE)", 72, 780),
        (f"QUYET DINH so {decision_no}", 72, 750),
        ("V/v phe duyet quy hoach phan khu DemoDistrict (SYNTHETIC)", 72, 720),
        (f"Ngay {day:02d} thang {month:02d} nam {year}", 72, 700),
        ("Dieu 1: Phe duyet noi dung quy hoach phan khu DemoDistrict.", 72, 660),
        ("Dieu 2: Pham vi ranh gioi quy hoach: toan bo dia ban DemoDistrict.", 72, 640),
        ("Du lieu nay la FIXTURE TONG HOP - khong co gia tri phap ly.", 72, 600),
    ]
    content = "BT /F1 12 Tf\n"
    for text, x, y in lines:
        content += f"1 0 0 1 {x} {y} Tm ({text}) Tj\n"
    content += "ET\n"
    stream = content.encode("latin-1")
    objs = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objs.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
    )
    objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n" % (len(objs) + 1))
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    )
    path.write_bytes(out.getvalue())


def make_scan_png(path: Path):
    """Hand-draw a fake 'scanned map' PNG (no PIL needed): grid + zones + arrow."""
    W = H = 400
    img = np.full((H, W, 3), 245, dtype=np.uint8)
    # paper edge
    img[0:4, :] = 90
    img[-4:, :] = 90
    img[:, 0:4] = 90
    img[:, -4:] = 90
    # grid every 40px
    for g in range(40, 400, 40):
        img[g, :] = (200, 200, 200)
        img[:, g] = (200, 200, 200)
    # zone rectangles (residential green industrial like v1)
    img[20:180, 20:180] = (255, 220, 160)
    img[20:180, 220:380] = (170, 220, 170)
    img[220:380, 20:180] = (140, 200, 140)
    img[220:380, 220:380] = (220, 180, 180)
    # roads
    img[196:204, 10:390] = (60, 60, 60)
    img[10:390, 196:204] = (60, 60, 60)
    # north arrow (simple triangle)
    for i in range(40):
        img[30 + i, 360 - i // 3 : 360 + i // 3] = (20, 20, 20)
    # write PNG
    raw = b"".join(b"\x00" + img[r].tobytes() for r in range(H))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def make_cog(path: Path):
    """The 'already georeferenced' version of the scan — a real GeoTIFF COG."""
    W = H = 400
    rng = np.random.default_rng(42)
    img = np.full((3, H, W), 245, dtype=np.uint8)
    for g in range(40, 400, 40):
        img[:, g, :] = 200
        img[:, :, g] = 200
    img[:, 20:180, 20:180] = np.array([255, 220, 160])[:, None, None]
    img[:, 196:204, 10:390] = 60
    img[:, 10:390, 196:204] = 60
    noise = rng.integers(0, 14, (3, H, W), dtype=np.uint8)
    img = np.clip(img.astype(np.int16) - noise, 0, 255).astype(np.uint8)
    # georeference: PNG pixel space maps linearly onto the district bbox
    west = LON0
    north = LAT0 + DEG
    res = DEG / W
    transform = from_origin(west, north, res, res)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=H,
        width=W,
        count=3,
        dtype="uint8",
        crs="EPSG:4326",
        transform=transform,
        tiled=True,
        blockxsize=256,
        blockysize=256,
        compress="deflate",
    ) as dst:
        dst.write(img)
        dst.build_overviews([2, 4], rasterio.enums.Resampling.nearest)
        dst.update_tags(ns="rio_overview", resampling="nearest")


def main():
    for sub in ("documents", "gis", "scans", "georeferenced"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)

    # --- GIS v1
    g, fd = land_use_v1()
    write_gpkg(
        OUT / "gis" / "land_use_v1.gpkg",
        "quy_hoach_su_dung_dat",
        g,
        fd,
        [
            ("ma_loai_dat", "OFTString"),
            ("ten_loai_dat", "OFTString"),
            ("dien_tich_ha", "OFTReal"),
            ("synthetic", "OFTInteger"),
        ],
        "Polygon",
    )
    g, fd = transport(1)
    write_gpkg(
        OUT / "gis" / "transport_v1.gpkg",
        "quy_hoach_giao_thong",
        g,
        fd,
        [
            ("ma_tuyen", "OFTString"),
            ("cap_duong", "OFTString"),
            ("do_rong_m", "OFTReal"),
            ("synthetic", "OFTInteger"),
        ],
        "LineString",
    )
    g, fd = boundary()
    write_gpkg(
        OUT / "gis" / "boundary.gpkg",
        "ranh_gioi",
        g,
        fd,
        [("ten_don_vi", "OFTString"), ("cap", "OFTString"), ("synthetic", "OFTInteger")],
        "Polygon",
    )

    # --- GIS v2
    g, fd = land_use_v2()
    write_gpkg(
        OUT / "gis" / "land_use_v2.gpkg",
        "quy_hoach_su_dung_dat",
        g,
        fd,
        [
            ("ma_loai_dat", "OFTString"),
            ("ten_loai_dat", "OFTString"),
            ("dien_tich_ha", "OFTReal"),
            ("synthetic", "OFTInteger"),
        ],
        "Polygon",
    )
    g, fd = transport(2)
    write_gpkg(
        OUT / "gis" / "transport_v2.gpkg",
        "quy_hoach_giao_thong",
        g,
        fd,
        [
            ("ma_tuyen", "OFTString"),
            ("cap_duong", "OFTString"),
            ("do_rong_m", "OFTReal"),
            ("synthetic", "OFTInteger"),
        ],
        "LineString",
    )

    # --- documents
    make_pdf(OUT / "documents" / "qd_001_phe_duyet_v1.pdf", "QD-001", "001/QD-UBND-MX", 1, 3, 2024)
    make_pdf(
        OUT / "documents" / "qd_002_phe_duyet_v2.pdf", "QD-002", "002/QD-UBND-MX", 15, 12, 2024
    )

    # --- rasters
    make_scan_png(OUT / "scans" / "ban_do_quy_hoach_scan.png")
    make_cog(OUT / "georeferenced" / "ban_do_quy_hoach_cog.tif")

    # keep a stable copy of the scan + cog for georef demo fixtures
    gcp_dir = OUT / "georef_gcps"
    gcp_dir.mkdir(exist_ok=True)
    print(f"fixtures written to {OUT}")


if __name__ == "__main__":
    main()
