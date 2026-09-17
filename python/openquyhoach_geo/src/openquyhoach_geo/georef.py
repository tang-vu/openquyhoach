"""Ground-control-point georeferencing math.

Manual + assisted georeferencing share this module. Solvers are deterministic
least-squares; assisted pipelines feed *candidate* GCPs through RANSAC
rejection here — suggestions never bypass the math or the review gate.

Supported transforms (docs/architecture/georeferencing.md):

* ``affine``       — 6 params, ≥3 GCPs (default; always supported)
* ``polynomial_2`` — 12 params, ≥6 GCPs (gentle scan warp)
* ``polynomial_3`` — 20 params, ≥10 GCPs
* ``projective``   — 8 params, ≥4 GCPs (homography; strong perspective)
* ``tps``          — thin-plate spline, ≥3 GCPs (exact at GCPs)
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import combinations

import numpy as np

MIN_GCPS = {"affine": 3, "polynomial_2": 6, "polynomial_3": 10, "projective": 4, "tps": 3}


@dataclass
class GCP:
    pixel_x: float
    pixel_y: float
    map_x: float
    map_y: float
    enabled: bool = True
    id: str | None = None
    origin: str = "manual"  # manual|ocr|ai|import
    residual: float | None = None


@dataclass
class TransformResult:
    transform_type: str
    coefficients: list[float]
    rmse: float
    residuals: dict[str, float]  # gcp id -> residual in map units
    used_gcps: int
    rejected: list[str] = field(default_factory=list)

    def apply(self, px: float, py: float) -> tuple[float, float]:
        return apply_transform(self.transform_type, self.coefficients, px, py)


def _design_poly(px: float, py: float, degree: int) -> list[float]:
    return [
        px**i * py**j
        for total in range(degree, -1, -1)
        for i in range(total, -1, -1)
        for j in [total - i]
    ]


def _design(t: str, px: float, py: float) -> list[float]:
    if t == "affine":
        return [px, py, 1.0]
    if t == "polynomial_2":
        return _design_poly(px, py, 2)
    if t == "polynomial_3":
        return _design_poly(px, py, 3)
    raise ValueError(t)


def _fit_least_squares(gcps: list[GCP], t: str) -> np.ndarray:
    A = np.array([_design(t, g.pixel_x, g.pixel_y) for g in gcps])
    bx = np.array([g.map_x for g in gcps])
    by = np.array([g.map_y for g in gcps])
    cx, *_ = np.linalg.lstsq(A, bx, rcond=None)
    cy, *_ = np.linalg.lstsq(A, by, rcond=None)
    return np.concatenate([cx, cy])


def _fit_projective(gcps: list[GCP]) -> np.ndarray:
    """Homography pixel->map via DLT. Returns 8 coefficients."""
    n = len(gcps)
    A = np.zeros((2 * n, 8))
    b = np.zeros(2 * n)
    for i, g in enumerate(gcps):
        u, v, x, y = g.pixel_x, g.pixel_y, g.map_x, g.map_y
        A[2 * i] = [u, v, 1, 0, 0, 0, -x * u, -x * v]
        A[2 * i + 1] = [0, 0, 0, u, v, 1, -y * u, -y * v]
        b[2 * i] = x
        b[2 * i + 1] = y
    h, *_ = np.linalg.lstsq(A, b, rcond=None)
    return h


def _tps_kernel(r2: np.ndarray) -> np.ndarray:
    r = np.sqrt(np.maximum(r2, 0))
    return np.where(r2 > 0, r2 * np.log(np.maximum(r, 1e-300)), 0.0)


def _fit_tps(gcps: list[GCP]) -> np.ndarray:
    """Thin-plate spline. Packed coeffs: [Wx(n+3), Wy(n+3), ax(n), ay(n)] → 4n+6."""
    n = len(gcps)
    px = np.array([g.pixel_x for g in gcps])
    py = np.array([g.pixel_y for g in gcps])
    r2 = (px[:, None] - px[None, :]) ** 2 + (py[:, None] - py[None, :]) ** 2
    K = _tps_kernel(r2)
    P = np.column_stack([np.ones(n), px, py])
    L = np.block([[K, P], [P.T, np.zeros((3, 3))]])
    Y = np.vstack([np.array([[g.map_x, g.map_y] for g in gcps]), np.zeros((3, 2))])
    W = np.linalg.solve(L, Y)  # (n+3, 2): n kernel weights + [a0, ax, ay]
    return np.concatenate([W[:, 0], W[:, 1], px, py])


def _fit_once(gcps: list[GCP], t: str) -> np.ndarray:
    if t == "projective":
        return _fit_projective(gcps)
    if t == "tps":
        return _fit_tps(gcps)
    return _fit_least_squares(gcps, t)


def apply_transform(t: str, coeffs: list[float], px: float, py: float) -> tuple[float, float]:
    c = np.asarray(coeffs, dtype=float)
    if t in {"affine", "polynomial_2", "polynomial_3"}:
        half = len(c) // 2
        row = _design(t, px, py)
        return float(np.dot(row, c[:half])), float(np.dot(row, c[half:]))
    if t == "projective":
        denom = c[6] * px + c[7] * py + 1.0
        if abs(denom) < 1e-12:
            return (math.nan, math.nan)
        x = (c[0] * px + c[1] * py + c[2]) / denom
        y = (c[3] * px + c[4] * py + c[5]) / denom
        return (float(x), float(y))
    if t == "tps":
        n = (len(c) - 6) // 4
        half = n + 3
        wx, wy = c[:half], c[half : 2 * half]
        ax, ay = c[2 * half : 2 * half + n], c[2 * half + n : 2 * half + 2 * n]
        r2 = (ax - px) ** 2 + (ay - py) ** 2
        U = _tps_kernel(r2)
        x = float(U @ wx[:n] + wx[n] + wx[n + 1] * px + wx[n + 2] * py)
        y = float(U @ wy[:n] + wy[n] + wy[n + 1] * px + wy[n + 2] * py)
        return x, y
    raise ValueError(t)


def compute_transform(
    gcps: Sequence[dict | GCP],
    *,
    transform_type: str = "affine",
    ransac: bool = True,
    ransac_threshold: float | None = None,
) -> TransformResult:
    """Fit a transform over enabled GCPs, with optional RANSAC rejection.

    Rejected GCP ids are reported in the result — never silently dropped.
    """
    pts = [
        g
        if isinstance(g, GCP)
        else GCP(**{k: v for k, v in g.items() if k in GCP.__dataclass_fields__})
        for g in gcps
    ]
    used = [g for g in pts if g.enabled]
    min_req = MIN_GCPS.get(transform_type)
    if min_req is None:
        raise ValueError(f"unknown transform {transform_type!r}")
    if len(used) < min_req:
        raise ValueError(f"{transform_type} requires >= {min_req} enabled GCPs, got {len(used)}")

    rejected: list[str] = []
    if ransac and len(used) > min_req:
        used, rejected = _ransac(used, transform_type, ransac_threshold)
        if len(used) < min_req:
            raise ValueError("RANSAC removed too many GCPs to fit the transform")

    coeffs = _fit_once(used, transform_type)

    residuals: dict[str, float] = {}
    se = 0.0
    for i, g in enumerate(used):
        mx, my = apply_transform(transform_type, coeffs.tolist(), g.pixel_x, g.pixel_y)
        r = math.hypot(mx - g.map_x, my - g.map_y)
        residuals[g.id or str(i)] = r
        se += r * r
    rmse = math.sqrt(se / len(used))
    return TransformResult(
        transform_type=transform_type,
        coefficients=coeffs.tolist(),
        rmse=rmse,
        residuals=residuals,
        used_gcps=len(used),
        rejected=rejected,
    )


def _auto_threshold(gcps: list[GCP]) -> float:
    """Scale-aware inlier threshold: ~2px of map error.

    Estimates map-units-per-pixel from the GCP bounding boxes, so the
    threshold adapts to the map's scale instead of a fixed epsilon.
    """
    pxs = [g.pixel_x for g in gcps]
    pys = [g.pixel_y for g in gcps]
    mxs = [g.map_x for g in gcps]
    mys = [g.map_y for g in gcps]
    px_span = math.hypot(max(pxs) - min(pxs), max(pys) - min(pys)) or 1.0
    map_span = math.hypot(max(mxs) - min(mxs), max(mys) - min(mys))
    return max(2.0 * map_span / px_span, 1e-9)


def _subset_invertible(subset: list[GCP], t: str) -> bool:
    """Skip minimal subsets whose design matrix is rank-deficient —
    e.g. three collinear pixels make an affine fit that is exact on those
    points yet garbage elsewhere, which would poison the consensus score."""
    if t in {"projective", "tps"}:
        return True  # handled implicitly by solve failures
    A = np.array([_design(t, g.pixel_x, g.pixel_y) for g in subset])
    return int(np.linalg.matrix_rank(A)) == A.shape[1]


def _ransac(gcps: list[GCP], t: str, threshold: float | None) -> tuple[list[GCP], list[str]]:
    """Deterministic exhaustive-minimal-subset RANSAC: evaluates every minimal
    subset and keeps the largest consensus set. Fully deterministic — no RNG —
    so the outcome is reproducible and auditable."""
    min_req = MIN_GCPS[t]
    thr = threshold if threshold is not None else _auto_threshold(gcps)
    best_inliers: list[GCP] = []
    best_err = float("inf")
    for subset in combinations(gcps, min_req):
        if not _subset_invertible(list(subset), t):
            continue
        try:
            coeffs = _fit_once(list(subset), t)
        except Exception:
            continue
        errs = [
            math.hypot(
                apply_transform(t, coeffs.tolist(), g.pixel_x, g.pixel_y)[0] - g.map_x,
                apply_transform(t, coeffs.tolist(), g.pixel_x, g.pixel_y)[1] - g.map_y,
            )
            for g in gcps
        ]
        inliers = [g for g, e in zip(gcps, errs, strict=True) if e <= thr]
        # tie-break on total inlier error so a tight fit beats a loose one
        err_sum = sum(e for g, e in zip(gcps, errs, strict=True) if e <= thr)
        if len(inliers) > len(best_inliers) or (
            len(inliers) == len(best_inliers) and err_sum < best_err
        ):
            best_inliers, best_err = inliers, err_sum
    if not best_inliers:
        return gcps, []
    keep = {id(g) for g in best_inliers}
    rejected = [g.id or "?" for g in gcps if id(g) not in keep]
    return best_inliers, rejected
