"""SSRF guard + archive safety — hostile-input tests."""

from __future__ import annotations

import zipfile

import pytest
from openquyhoach_core.errors import FetchBlockedError, ValidationError
from openquyhoach_core.security import (
    check_url_allowed,
    safe_extract_zip,
    sniff_format,
)


class TestSsrf:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/x",
            "http://127.0.0.53/x",
            "http://[::1]/x",
            "http://0.0.0.0/x",
            "http://10.0.0.4/x",
            "http://172.16.3.1/x",
            "http://192.168.1.1/x",
            "http://169.254.169.254/latest/meta-data",  # cloud metadata
            "ftp://example.com/x",
            "file:///etc/passwd",
            "gopher://x",
        ],
    )
    def test_blocked(self, url):
        with pytest.raises(FetchBlockedError):
            check_url_allowed(url)

    def test_localhost_blocked(self):
        # resolves via DNS — skip silently if offline
        try:
            check_url_allowed("http://localhost/x")
        except FetchBlockedError:
            return  # expected
        pytest.fail("localhost was allowed")

    @pytest.mark.parametrize(
        "url",
        [
            "https://8.8.8.8/x",
            "http://1.1.1.1/x",
        ],
    )
    def test_public_literal_allowed(self, url):
        assert check_url_allowed(url) == url


class TestZipSlip:
    def _zip(self, path, names):
        with zipfile.ZipFile(path, "w") as z:
            for n in names:
                z.writestr(n, b"x")

    def test_normal(self, tmp_path):
        z = tmp_path / "a.zip"
        self._zip(z, ["a/b.txt", "c.txt"])
        out = safe_extract_zip(z, tmp_path / "out")
        assert len(out) == 2
        assert all(str(p).startswith(str(tmp_path / "out")) for p in out)

    def test_traversal_blocked(self, tmp_path):
        for names in (["../evil.txt"], ["a/../../evil.txt"], ["/abs/path"]):
            z = tmp_path / "bad.zip"
            self._zip(z, names)
            with pytest.raises(ValidationError):
                safe_extract_zip(z, tmp_path / "out")


class TestSniff:
    def test_magic(self):
        assert sniff_format(b"\x89PNG\r\n\x1a\n" + b"0" * 20, "x.bin") == "png"
        assert sniff_format(b"%PDF-1.4 rest", "x.bin") == "pdf"
        assert sniff_format(b"PK\x03\x04" + b"0" * 20, "x.bin") == "zip"
        assert sniff_format(b"II*\x00" + b"0" * 20, "x.bin") == "tiff"

    def test_gpkg_sqlite(self):
        # GPKG is SQLite with a gpkg name → must not be classified 'sqlite'
        assert sniff_format(b"SQLite format 3\x00" + b"0" * 10, "a.gpkg") == "gpkg"

    def test_extension_fallback(self):
        assert sniff_format(b'{"type":"FeatureCollection"}', "a.geojson") == "geojson"
        assert sniff_format(b"random", "a.shp") == "shp"
        assert sniff_format(b"random", "a.unknownext") is None

    def test_jsvar_geojson(self):
        # var name = {...FeatureCollection...}; — quyhoach.hanoi.vn shape
        body = b'var qhpk = {"type":"FeatureCollection","features":[]};'
        assert sniff_format(body, "qhpk.js") == "jsvar_geojson"
        # leading whitespace / $-identifiers still match
        body2 = b'  var $x_1={ "type": "FeatureCollection", "features": [] };'
        assert sniff_format(body2, "layer.js") == "jsvar_geojson"

    def test_jsvar_geojson_negative(self):
        # .js without a var-wrapped FeatureCollection must not classify
        assert sniff_format(b'alert("hi")', "a.js") is None
        assert sniff_format(b'var x = [1,2,3];', "a.js") is None
        # var-FC pattern but wrong extension → not jsvar_geojson
        body = b'var qhpk = {"type":"FeatureCollection","features":[]};'
        assert sniff_format(body, "qhpk.txt") is None
        # FeatureCollection must appear in the sniffed header
        assert sniff_format(b"var x = {", "a.js") is None
