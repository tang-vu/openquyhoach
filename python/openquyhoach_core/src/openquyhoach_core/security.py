"""Fetch & file safety: SSRF guard, archive limits, MIME sniffing."""

from __future__ import annotations

import ipaddress
import socket
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from .errors import FetchBlockedError, ValidationError
from .settings import Settings, get_settings

ALLOWED_SCHEMES = {"http", "https"}

# Magic bytes → format label. Intentionally conservative — the detector never
# *trusts* these, it only narrows the parser we try.
MAGIC = [
    (b"PK\x03\x04", "zip"),
    (b"%PDF", "pdf"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"SQLite format 3\x00", "sqlite"),  # GeoPackage is SQLite — refined by inspection
    (b"{", "json"),
    (b"[", "json"),
    (b"<", "xmlish"),
]


def check_url_allowed(url: str, settings: Settings | None = None) -> str:
    """SSRF guard for user-/source-submitted URLs.

    Rejects non-http(s) schemes and, unless explicitly allowed, URLs whose
    host resolves to loopback/private/link-local/reserved addresses.
    """
    s = settings or get_settings()
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise FetchBlockedError(f"scheme {parsed.scheme!r} not allowed", detail={"url": url})
    host = parsed.hostname
    if not host:
        raise FetchBlockedError("URL has no host", detail={"url": url})
    if s.fetch_allow_private_ips:
        return url
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise FetchBlockedError(f"DNS resolution failed for {host}", detail={"url": url}) from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise FetchBlockedError(
                f"host {host} resolves to non-public address {ip}",
                detail={"url": url, "ip": str(ip)},
            )
    return url


def sniff_format(header: bytes, filename: str | None = None) -> str | None:
    for magic, fmt in MAGIC:
        if header.startswith(magic):
            if fmt == "sqlite" and filename and filename.lower().endswith(".gpkg"):
                return "gpkg"
            if fmt == "json" and filename:
                low = filename.lower()
                if low.endswith((".geojson", ".json")):
                    return "geojson"
            return fmt
    if filename:
        low = filename.lower()
        for ext, fmt in {
            ".gpkg": "gpkg",
            ".geojson": "geojson",
            ".json": "json",
            ".shp": "shp",
            ".tif": "tiff",
            ".tiff": "tiff",
            ".kml": "kml",
            ".dxf": "dxf",
            ".dwg": "dwg",
            ".pdf": "pdf",
            ".zip": "zip",
        }.items():
            if low.endswith(ext):
                return fmt
    return None


def check_archive_safety(
    path: str | Path,
    *,
    max_members: int = 1000,
    max_total_uncompressed: int = 2 * 1024**3,
    max_ratio: float = 200.0,
) -> list[zipfile.ZipInfo]:
    """ZIP-bomb/traversal guard. Returns member list if the archive is safe."""
    infos: list[zipfile.ZipInfo] = []
    total = 0
    compressed = 0
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            infos.append(info)
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValidationError(f"unsafe archive member path: {name!r}")
            total += info.file_size
            compressed += info.compress_size
            if len(infos) > max_members:
                raise ValidationError(f"archive has more than {max_members} members")
            if total > max_total_uncompressed:
                raise ValidationError("archive expands beyond allowed size")
        if compressed and total / max(compressed, 1) > max_ratio:
            raise ValidationError("suspicious archive compression ratio (zip bomb)")
    return infos


def safe_extract_zip(path: str | Path, dest: str | Path) -> list[Path]:
    """Extract after `check_archive_safety`; writes only under `dest`."""
    check_archive_safety(path)
    dest_path = Path(dest).resolve()
    out: list[Path] = []
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            target = (dest_path / info.filename).resolve()
            if dest_path not in target.parents and target != dest_path:
                raise ValidationError(f"member escapes destination: {info.filename!r}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                remaining = info.file_size
                while remaining > 0:
                    chunk = src.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    dst.write(chunk)
                    remaining -= len(chunk)
            out.append(target)
    return out
