"""PMTiles v3 writer/reader — spec conformance + roundtrip."""

from __future__ import annotations

import io

import pytest
from openquyhoach_geo.pmtiles import PMTilesReader, Tile, write_pmtiles

pytestmark = pytest.mark.unit


def _tile(z, x, y, payload: bytes):
    return Tile(z=z, x=x, y=y, data=payload)


class TestWrite:
    def test_header_spec(self):
        buf = io.BytesIO()
        write_pmtiles([_tile(0, 0, 0, b"abc")], metadata={}, out=buf)
        data = buf.getvalue()
        assert data[:7] == b"PMTiles"
        assert data[7] == 3  # spec version

    def test_empty(self):
        buf = io.BytesIO()
        stats = write_pmtiles([], metadata={}, out=buf)
        assert stats["num_tiles"] == 0
        assert buf.getvalue()[:7] == b"PMTiles"

    def test_metadata_json(self):
        buf = io.BytesIO()
        write_pmtiles(
            [_tile(1, 1, 1, b"xyz")],
            metadata={"hello": "world", "vector_layers": [{"id": "l"}]},
            out=buf,
        )
        r = PMTilesReader(buf.getvalue())
        meta = r.metadata()
        assert meta["hello"] == "world"


class TestRead:
    def test_roundtrip(self):
        tiles = [
            _tile(0, 0, 0, b"z0"),
            _tile(1, 0, 0, b"z1a"),
            _tile(1, 1, 1, b"z1b"),
            _tile(12, 3252, 1804, b"deep"),
        ]
        buf = io.BytesIO()
        write_pmtiles(
            tiles,
            metadata={"m": 1},
            out=buf,
            min_lon=105.8,
            min_lat=20.9,
            max_lon=105.95,
            max_lat=20.97,
        )
        r = PMTilesReader(buf.getvalue())
        assert r.get_tile(0, 0, 0) == b"z0"
        assert r.get_tile(1, 0, 0) == b"z1a"
        assert r.get_tile(1, 1, 1) == b"z1b"
        assert r.get_tile(12, 3252, 1804) == b"deep"
        assert r.get_tile(5, 9, 9) is None
        assert r.metadata()["m"] == 1

    def test_deterministic_bytes(self):
        tiles = [_tile(2, x, y, f"t{x}{y}".encode()) for x in range(4) for y in range(4)]
        b1 = io.BytesIO()
        b2 = io.BytesIO()
        write_pmtiles(tiles, metadata={"k": "v"}, out=b1)
        write_pmtiles(tiles, metadata={"k": "v"}, out=b2)
        assert b1.getvalue() == b2.getvalue()

    def test_duplicate_tile_rejected(self):
        with pytest.raises(ValueError):
            write_pmtiles(
                [_tile(1, 0, 0, b"a"), _tile(1, 0, 0, b"b")], metadata={}, out=io.BytesIO()
            )
