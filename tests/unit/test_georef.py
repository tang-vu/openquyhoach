"""Georeferencing math — deterministic, auditable, outlier-aware."""

from __future__ import annotations

import math

import pytest
from openquyhoach_geo.georef import apply_transform, compute_transform


def _grid_gcps(nx=3, ny=3, scale=0.001, off=(10.0, 20.0)):
    """Pixel grid → map coords with a known affine relation."""
    gcps = []
    k = 0
    for iy in range(ny):
        for ix in range(nx):
            px, py = ix * 100.0, iy * 100.0
            gcps.append(
                {
                    "id": f"g{k}",
                    "pixel_x": px,
                    "pixel_y": py,
                    "map_x": off[0] + px * scale,
                    "map_y": off[1] + py * scale * 2,
                    "enabled": True,
                }
            )
            k += 1
    return gcps


class TestAffine:
    def test_exact_fit(self):
        r = compute_transform(_grid_gcps(), transform_type="affine")
        assert r.rmse < 1e-9
        x, y = r.apply(50.0, 50.0)
        assert math.isclose(x, 10.05, abs_tol=1e-6)
        assert math.isclose(y, 20.10, abs_tol=1e-6)

    def test_min_gcps_enforced(self):
        with pytest.raises(ValueError, match=">= 3"):
            compute_transform(_grid_gcps(1, 2), transform_type="affine")

    def test_disabled_gcps_ignored(self):
        gcps = _grid_gcps()
        gcps[0]["enabled"] = False
        r = compute_transform(gcps, transform_type="affine")
        assert r.used_gcps == len(gcps) - 1


class TestRansac:
    def test_outlier_rejected_and_reported(self):
        gcps = _grid_gcps(4, 4)
        gcps.append(
            {
                "id": "bad",
                "pixel_x": 150.0,
                "pixel_y": 150.0,
                "map_x": 99.0,
                "map_y": 99.0,
                "enabled": True,
            }
        )
        r = compute_transform(gcps, transform_type="affine")
        assert "bad" in r.rejected
        assert r.used_gcps == len(gcps) - 1
        assert r.rmse < 1e-6

    def test_rejection_is_deterministic(self):
        gcps = _grid_gcps(3, 3)
        gcps.append(
            {"id": "bad", "pixel_x": 50, "pixel_y": 50, "map_x": 0.0, "map_y": 0.0, "enabled": True}
        )
        r1 = compute_transform(gcps, transform_type="affine")
        r2 = compute_transform(gcps, transform_type="affine")
        assert r1.rejected == r2.rejected
        assert r1.coefficients == r2.coefficients

    def test_no_ransac(self):
        gcps = _grid_gcps()
        gcps.append(
            {"id": "bad", "pixel_x": 50, "pixel_y": 50, "map_x": 0.0, "map_y": 0.0, "enabled": True}
        )
        r = compute_transform(gcps, transform_type="affine", ransac=False)
        assert r.rejected == []
        assert r.used_gcps == len(gcps)


class TestOtherTransforms:
    def test_projective(self):
        gcps = _grid_gcps(2, 2)
        r = compute_transform(gcps, transform_type="projective", ransac=False)
        assert r.rmse < 1e-6
        x, _y = r.apply(50.0, 50.0)
        assert math.isclose(x, 10.05, abs_tol=1e-4)

    def test_polynomial_2(self):
        gcps = _grid_gcps(4, 4)  # 16 ≥ 6
        r = compute_transform(gcps, transform_type="polynomial_2")
        assert r.rmse < 1e-6

    def test_polynomial_3_needs_ten(self):
        with pytest.raises(ValueError):
            compute_transform(_grid_gcps(2, 3), transform_type="polynomial_3")

    def test_tps_exact_at_gcps(self):
        gcps = _grid_gcps(3, 3)
        r = compute_transform(gcps, transform_type="tps")
        for g in gcps:
            x, y = r.apply(g["pixel_x"], g["pixel_y"])
            assert math.isclose(x, g["map_x"], abs_tol=1e-6)
            assert math.isclose(y, g["map_y"], abs_tol=1e-6)


class TestApply:
    def test_affine_coefficients_layout(self):
        # [a,b,c | d,e,f]: x' = a*px + b*py + c ; y' = d*px + e*py + f
        x, y = apply_transform("affine", [1, 0, 100, 0, 1, 200], 5, 7)
        assert (x, y) == (105.0, 207.0)
