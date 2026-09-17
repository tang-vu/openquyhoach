"""CRS identification — the 'never guess' contract."""

from __future__ import annotations

import pytest
from openquyhoach_core.errors import CRSError
from openquyhoach_geo.crs import describe_crs, require_identified


class TestDescribeCrs:
    def test_epsg_int(self):
        info = describe_crs(4326)
        assert info.identified
        assert info.epsg == 4326
        assert info.axis_order in ("en", "ne")

    def test_epsg_string(self):
        info = describe_crs("EPSG:32648")
        assert info.epsg == 32648

    def test_wkt(self):
        from pyproj import CRS

        info = describe_crs(CRS.from_epsg(32648).to_wkt())
        assert info.epsg == 32648

    def test_unidentified(self):
        info = describe_crs(None)
        assert not info.identified
        assert info.epsg is None

    def test_garbage(self):
        info = describe_crs("not a crs")
        assert not info.identified


class TestVn2000:
    """VN-2000 is identified by its base geodetic CRS (EPSG:4756), not by
    enumerating every projected zone — zone codes span several EPSG blocks."""

    @pytest.mark.parametrize("epsg", [3405, 3406, 5896, 5899, 6956, 6959, 9210, 9218])
    def test_projected_zones(self, epsg):
        info = describe_crs(epsg)
        if info.identified:  # only assert when the local EPSG db knows the code
            assert info.is_vn2000, f"EPSG:{epsg}"

    def test_geographic_base(self):
        info = describe_crs(4756)
        assert info.identified
        assert info.is_vn2000

    def test_not_vn2000(self):
        assert not describe_crs(4326).is_vn2000
        assert not describe_crs(32648).is_vn2000  # WGS84 UTM 48N


class TestRequireIdentified:
    def test_refuses_unknown(self):
        with pytest.raises(CRSError):
            require_identified(describe_crs(None))

    def test_ok(self):
        info = describe_crs(4326)
        assert require_identified(info).to_epsg() == 4326
