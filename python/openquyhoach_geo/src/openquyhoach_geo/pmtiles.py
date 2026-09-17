"""PMTiles v3 reader/writer (spec: https://github.com/protomaps/PMTiles).

Implemented directly rather than via a third-party lib so we control
determinism: identical tile input always produces a byte-identical archive
(which makes publication checksums reproducible).

Layout: header(127B) | root dir | JSON metadata | leaf dirs | tile data.
Directories are varint-encoded; gzip is used for internal compression.
"""

from __future__ import annotations

import gzip
import io
import json
import struct
from collections.abc import Iterable
from dataclasses import dataclass
from typing import BinaryIO

MAGIC = b"PMTiles"
SPEC_VERSION = 3
HEADER_LEN = 127
MAX_ROOT_BYTES = 16 * 1024  # spec guidance; larger roots get leaf dirs
LEAF_TARGET_BYTES = 512 * 1024

COMP_NONE, COMP_GZIP = 1, 2
TILE_MVT = 1
TILE_PNG, TILE_JPEG = 2, 3


@dataclass(order=True)
class DirEntry:
    tile_id: int
    offset: int  # offset into tile_data section
    length: int
    run_length: int = 1


def zxy_to_tileid(z: int, x: int, y: int) -> int:
    """PMTiles tile_id: pyramid offset + Hilbert position within zoom level."""
    if z == 0:
        return 0
    if z > 26:
        raise ValueError("zoom > 26 unsupported by PMTiles tile_id")
    n = 1 << z
    if not (0 <= x < n and 0 <= y < n):
        raise ValueError(f"tile {z}/{x}/{y} out of range")
    acc = ((1 << (2 * z)) - 1) // 3
    d = 0
    xx, yy = x, y
    s = n >> 1
    while s > 0:
        rx = 1 if (xx & s) else 0
        ry = 1 if (yy & s) else 0
        d += s * s * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                xx = n - 1 - xx
                yy = n - 1 - yy
            xx, yy = yy, xx
        s >>= 1
    return acc + d


def tileid_to_zxy(tile_id: int) -> tuple[int, int, int]:
    """Inverse of zxy_to_tileid — used by readers/tests."""
    import math

    if tile_id == 0:
        return (0, 0, 0)
    # zoom level = floor(log3-ish); find z such that acc(z) <= id < acc(z+1)
    z = int(math.log(tile_id * 3 + 1, 4))
    while ((1 << (2 * z)) - 1) // 3 > tile_id:
        z -= 1
    while ((1 << (2 * (z + 1))) - 1) // 3 <= tile_id:
        z += 1
    acc = ((1 << (2 * z)) - 1) // 3
    d = tile_id - acc
    n = 1 << z
    x = y = 0
    t = d
    s = 1
    while s < n:
        rx = 1 & (t // 2)
        ry = 1 & (t ^ rx)
        # rotate
        if ry == 0:
            if rx == 1:
                x = s - 1 - x
                y = s - 1 - y
            x, y = y, x
        x += s * rx
        y += s * ry
        t //= 4
        s *= 2
    return (z, x, y)


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    shift = 0
    result = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


def serialize_directory(entries: list[DirEntry]) -> bytes:
    """Entries must be sorted by tile_id."""
    out = io.BytesIO()
    out.write(_varint(len(entries)))
    last = 0
    for e in entries:
        out.write(_varint(e.tile_id - last))
        last = e.tile_id
    for e in entries:
        out.write(_varint(e.run_length))
    for e in entries:
        out.write(_varint(e.length))
    for i, e in enumerate(entries):
        if i > 0 and e.offset == entries[i - 1].offset + entries[i - 1].length:
            out.write(_varint(0))
        else:
            out.write(_varint(e.offset + 1))
    return out.getvalue()


def deserialize_directory(buf: bytes) -> list[DirEntry]:
    n, pos = _read_varint(buf, 0)
    ids: list[int] = []
    last = 0
    for _ in range(n):
        delta, pos = _read_varint(buf, pos)
        last += delta
        ids.append(last)
    runs: list[int] = []
    for _ in range(n):
        v, pos = _read_varint(buf, pos)
        runs.append(v)
    lengths: list[int] = []
    for _ in range(n):
        v, pos = _read_varint(buf, pos)
        lengths.append(v)
    entries: list[DirEntry] = []
    for i in range(n):
        v, pos = _read_varint(buf, pos)
        offset = entries[i - 1].offset + entries[i - 1].length if v == 0 else v - 1
        entries.append(
            DirEntry(tile_id=ids[i], offset=offset, length=lengths[i], run_length=runs[i])
        )
    return entries


@dataclass
class Tile:
    z: int
    x: int
    y: int
    data: bytes


def write_pmtiles(
    tiles: Iterable[Tile | tuple[int, int, int, bytes]],
    metadata: dict,
    out: BinaryIO,
    *,
    tile_type: int = TILE_MVT,
    tile_compression: int = COMP_GZIP,
    min_lon: float = -180.0,
    min_lat: float = -85.0511,
    max_lon: float = 180.0,
    max_lat: float = 85.0511,
    center_zoom: int = 0,
    center_lon: float = 0.0,
    center_lat: float = 0.0,
) -> dict:
    """Write a PMTiles v3 archive. Returns stats for the publication manifest.

    Tiles may be gzip-compressed already (pass COMP_GZIP) — we do not
    recompress tile payloads, only directories/metadata.
    """
    norm: list[Tile] = [t if isinstance(t, Tile) else Tile(t[0], t[1], t[2], t[3]) for t in tiles]
    norm.sort(key=lambda t: zxy_to_tileid(t.z, t.x, t.y))
    ids = [zxy_to_tileid(t.z, t.x, t.y) for t in norm]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate tile coordinates in PMTiles input")

    tile_data = io.BytesIO()
    entries: list[DirEntry] = []
    for t in norm:
        offset = tile_data.tell()
        tile_data.write(t.data)
        entries.append(
            DirEntry(tile_id=zxy_to_tileid(t.z, t.x, t.y), offset=offset, length=len(t.data))
        )
    tile_data_bytes = tile_data.getvalue()

    meta_bytes = gzip.compress(json.dumps(metadata, separators=(",", ":")).encode(), mtime=0)

    # Root directory — split into leaves if it would exceed the guidance size.
    root_entries: list[DirEntry] = []
    leaf_bytes = b""
    root_serialized = serialize_directory(entries)
    if len(root_serialized) <= MAX_ROOT_BYTES:
        root_entries = entries
        root_raw = root_serialized
    else:
        leaves: list[tuple[int, bytes]] = []
        chunk: list[DirEntry] = []
        for e in entries:
            chunk.append(e)
            ser = serialize_directory(chunk)
            if len(ser) >= LEAF_TARGET_BYTES:
                leaves.append((chunk[0].tile_id, ser))
                chunk = []
        if chunk:
            leaves.append((chunk[0].tile_id, serialize_directory(chunk)))
        leaf_buf = io.BytesIO()
        for first_id, blob in leaves:
            off = leaf_buf.tell()
            leaf_buf.write(blob)
            # run_length=0 marks a leaf-dir pointer per the spec
            root_entries.append(
                DirEntry(tile_id=first_id, offset=off, length=len(blob), run_length=0)
            )
        leaf_bytes = leaf_buf.getvalue()
        root_raw = serialize_directory(root_entries)

    root_gz = gzip.compress(root_raw, mtime=0)
    leaf_gz = gzip.compress(leaf_bytes, mtime=0) if leaf_bytes else b""

    root_off = HEADER_LEN
    meta_off = root_off + len(root_gz)
    leaf_off = meta_off + len(meta_bytes)
    data_off = leaf_off + len(leaf_gz)

    min_zoom = min((t.z for t in norm), default=0)
    max_zoom = max((t.z for t in norm), default=0)

    header = struct.pack(
        "<7sB" + "Q" * 11 + "BBBBBB" + "iiii" + "B" + "ii",
        MAGIC,
        SPEC_VERSION,
        root_off,
        len(root_gz),
        meta_off,
        len(meta_bytes),
        leaf_off,
        len(leaf_gz),
        data_off,
        len(tile_data_bytes),
        sum(e.run_length for e in entries),
        len(entries),
        len(entries),  # no content dedup — every tile is a distinct payload
        1,  # clustered
        COMP_GZIP,
        tile_compression,
        tile_type,
        min_zoom,
        max_zoom,
        int(min_lon * 1e7),
        int(min_lat * 1e7),
        int(max_lon * 1e7),
        int(max_lat * 1e7),
        center_zoom,
        int(center_lon * 1e7),
        int(center_lat * 1e7),
    )
    assert len(header) == HEADER_LEN

    out.write(header)
    out.write(root_gz)
    out.write(meta_bytes)
    out.write(leaf_gz)
    out.write(tile_data_bytes)

    return {
        "num_tiles": len(norm),
        "num_tile_entries": len(entries),
        "min_zoom": min_zoom,
        "max_zoom": max_zoom,
        "tile_data_bytes": len(tile_data_bytes),
        "total_bytes": data_off + len(tile_data_bytes),
        "leaf_directories": bool(leaf_bytes),
    }


# ---------------------------------------------------------------------------
# Minimal reader — used by tests and by the API range-serving path.
# ---------------------------------------------------------------------------


@dataclass
class PMTilesHeader:
    root_offset: int
    root_length: int
    metadata_offset: int
    metadata_length: int
    leaf_offset: int
    leaf_length: int
    tile_data_offset: int
    tile_data_length: int
    num_addressed_tiles: int
    num_tile_entries: int
    num_tile_contents: int
    clustered: bool
    internal_compression: int
    tile_compression: int
    tile_type: int
    min_zoom: int
    max_zoom: int
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    center_zoom: int
    center_lon: float
    center_lat: float


def read_header(buf: bytes) -> PMTilesHeader:
    assert len(buf) >= HEADER_LEN and buf[:7] == MAGIC and buf[7] == SPEC_VERSION
    fields = struct.unpack("<7sB" + "Q" * 11 + "BBBBBB" + "iiii" + "B" + "ii", buf[:HEADER_LEN])
    return PMTilesHeader(
        root_offset=fields[2],
        root_length=fields[3],
        metadata_offset=fields[4],
        metadata_length=fields[5],
        leaf_offset=fields[6],
        leaf_length=fields[7],
        tile_data_offset=fields[8],
        tile_data_length=fields[9],
        num_addressed_tiles=fields[10],
        num_tile_entries=fields[11],
        num_tile_contents=fields[12],
        clustered=fields[13],
        internal_compression=fields[14],
        tile_compression=fields[15],
        tile_type=fields[16],
        min_zoom=fields[17],
        max_zoom=fields[18],
        min_lon=fields[19] / 1e7,
        min_lat=fields[20] / 1e7,
        max_lon=fields[21] / 1e7,
        max_lat=fields[22] / 1e7,
        center_zoom=fields[23],
        center_lon=fields[24] / 1e7,
        center_lat=fields[25] / 1e7,
    )


def _decompress(buf: bytes, compression: int) -> bytes:
    return gzip.decompress(buf) if compression == COMP_GZIP else buf


class PMTilesReader:
    """Offset/length reader over a seekable file-like object (or bytes)."""

    def __init__(self, source: BinaryIO | bytes):
        self._src = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
        self._src.seek(0)
        self.header = read_header(self._src.read(HEADER_LEN))
        self._dir_cache: dict[int, bytes] = {}

    def _read_at(self, offset: int, length: int) -> bytes:
        self._src.seek(offset)
        return self._src.read(length)

    def _resolve(self, tile_id: int) -> DirEntry | None:
        root_raw = _decompress(
            self._read_at(self.header.root_offset, self.header.root_length),
            self.header.internal_compression,
        )
        entries = deserialize_directory(root_raw)
        depth = 0
        while depth < 4:
            idx = -1
            for i, e in enumerate(entries):
                if e.tile_id <= tile_id:
                    idx = i
                else:
                    break
            if idx < 0:
                return None
            e = entries[idx]
            if e.run_length > 0:
                return e if tile_id - e.tile_id < e.run_length else None
            # leaf dir
            if e.tile_id in self._dir_cache:
                leaf_raw = self._dir_cache[e.tile_id]
            else:
                leaf_raw = _decompress(
                    self._read_at(self.header.leaf_offset + e.offset, e.length),
                    self.header.internal_compression,
                )
                self._dir_cache[e.tile_id] = leaf_raw
            entries = deserialize_directory(leaf_raw)
            depth += 1
        return None

    def get_tile(self, z: int, x: int, y: int) -> bytes | None:
        entry = self._resolve(zxy_to_tileid(z, x, y))
        if entry is None:
            return None
        raw = self._read_at(self.header.tile_data_offset + entry.offset, entry.length)
        return raw

    def metadata(self) -> dict:
        raw = _decompress(
            self._read_at(self.header.metadata_offset, self.header.metadata_length),
            self.header.internal_compression,
        )
        return json.loads(raw)
