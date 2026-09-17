"""Dynamic vector tile SQL (PostGIS ST_AsMVT) + tile math.

Tiles are generated in the database, not in Python — the bbox prefilter uses
the GiST index and geometry is clipped/simplified in Web Mercator.
"""

from __future__ import annotations

import mercantile
from sqlalchemy import text

TILE_SRID = 3857
EXTENT = 4096
BUFFER = 64


def tile_bounds_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    b = mercantile.xy_bounds(x, y, z)
    return (b.left, b.bottom, b.right, b.top)


def mvt_sql(where: str = "1=1") -> str:
    """Parameterized MVT query over published features.

    Columns exposed to the renderer are deliberate: id, classification,
    name, derivation_level, review_status — enough to style + badge, never
    the whole properties payload.
    """
    return f"""
WITH bounds AS (
  SELECT ST_TileEnvelope(:z, :x, :y) AS env
),
mvtgeom AS (
  SELECT
    f.id::text AS id,   -- attribute, not MVT feature-id (must be int64)
    f.source_object_name AS name,
    f.classification,
    f.source_object_code AS code,
    l.canonical_name AS layer,
    d.derivation_level,
    d.review_status,
    ST_AsMVTGeom(
      ST_Transform(ST_CurveToLine(f.geometry), {TILE_SRID}),
      bounds.env, {EXTENT}, {BUFFER}, true
    ) AS geom
  FROM features f
  JOIN layers l ON l.id = f.layer_id
  JOIN datasets d ON d.id = l.dataset_id
  CROSS JOIN bounds
  WHERE {where}
    AND f.geometry && ST_Transform(bounds.env, 4326)
)
SELECT ST_AsMVT(mvtgeom, :layer_name, {EXTENT}, 'geom') AS tile
FROM mvtgeom
"""


def fetch_mvt(
    engine,
    z: int,
    x: int,
    y: int,
    *,
    where: str = "1=1",
    params: dict | None = None,
    layer_name: str = "features",
) -> bytes | None:
    with engine.connect() as conn:
        row = conn.execute(
            text(mvt_sql(where)),
            {"z": z, "x": x, "y": y, "layer_name": layer_name, **(params or {})},
        ).fetchone()
    if not row or row[0] is None:
        return None
    return bytes(row[0])
