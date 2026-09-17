# Local PostGIS build — the stock postgis/postgis image isn't pullable in all
# environments, so we install the PGDG package on the official postgres image.
FROM postgres:17-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      postgresql-17-postgis-3 \
      postgresql-17-postgis-3-scripts \
 && rm -rf /var/lib/apt/lists/*

# Extensions are created by the first migration (postgis, unaccent, pg_trgm).
