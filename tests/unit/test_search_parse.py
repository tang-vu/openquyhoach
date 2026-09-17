"""Coordinate parsing for the search box (no DB)."""

from __future__ import annotations

import pytest
from openquyhoach_services.search import parse_coordinates

pytestmark = pytest.mark.unit


def test_lon_lat():
    assert parse_coordinates("105.8, 20.9") == (105.8, 20.9)
    assert parse_coordinates("105.8,20.9") == (105.8, 20.9)


def test_lat_lon_order_swapped():
    # '20.9, 105.8': first |val|<=90 and second >90 → treated as lat,lon
    assert parse_coordinates("20.9, 105.8") == (105.8, 20.9)


def test_maplibre_url():
    got = parse_coordinates("https://osm.org/#map=10/20.95/105.82")
    assert got == pytest.approx((105.82, 20.95))


def test_non_coord():
    assert parse_coordinates("quy hoạch đất ở") is None
    assert parse_coordinates("") is None
