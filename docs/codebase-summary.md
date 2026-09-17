# Codebase Summary

Monorepo: Python `uv` workspace + pnpm workspace. Python 3.12+ (dev used
3.14), lockfiles: `uv.lock`, `pnpm-lock.yaml`.

## Python packages (`python/`)

| Package | Contents |
|---|---|
| `openquyhoach_core` | `settings.py` (pydantic-settings, `OQH_*` env), `db.py` (engine/`session_scope`), `models/` (19 tables), `storage.py` (S3 + LocalStore, path-escape guard), `queue.py` (`JobQueue` protocol, inline + Redis), `security.py` (`check_url_allowed` SSRF guard), `provenance.py`, `hashing.py`, `errors.py`, `logging.py` |
| `openquyhoach_geo` | `crs.py` (CRSInfo, VN-2000 detect), `geom.py`, `vector.py` (pyogrio read/write), `raster.py`, `mvt.py` (ST_AsMVT SQL), `pmtiles.py` (v3 writer+reader), `georef.py` (affine/TPS, RANSAC) |
| `openquyhoach_quality` | `engine.py` (`run_rules`, `rule_catalog`, `ValidationContext`), `rules_geometry.py`, `rules_meta.py` |
| `openquyhoach_ingest` | `connectors/` (file, http, html, arcgis_rest, ogc, vector, raster, pdf, planning_portal), `sources.py` (descriptor schema+loader), `pipeline.py` (staged ingest), `pdfmeta.py`, `archive.py` (safe unzip), `jobs.py` |
| `openquyhoach_services` | `publish.py` (gate→tiles→PMTiles→manifest→flag, `read_publication_tile`), `compare.py` (changesets), `search.py`, `provenance.py`, `coverage.py`, `georef.py` |
| `openquyhoach_cli` | Typer app: `doctor`, `sources {validate,sync,list}`, `ingest`, `validate`, `publish`, `compare`, `db {migrate,seed}` |
| `openquyhoach_mcp` | MCP server: `search_planning`, `point_query`, `provenance_of`, `coverage` — read-only |

## Apps (`apps/`)

- `api` — `app.py` factory (+`app.setup()` for FastAPI≥0.141 lazy routers),
  `deps.py` (`PageDep`, admin token via `secrets.compare_digest`),
  `serializers.py`, routers: `browse`, `query`, `ingest`, `publish`,
  `georef`.
- `worker` — `main.py` (`--once`), `jobs.py` service-job registrations.
- `web` — Next.js 15 App Router, **static export** (`output:"export"`),
  MapLibre GL. `lib/api.ts` typed client; `components/`: `MapView`
  (MVT sources per publication, click→point query), `SearchBox`,
  `ProvenanceDrawer` (artifact sha256, decision no., legal status),
  `ComparePanel`, `AdminPanel` (review queue + publish). Port 3100.

## Other

- `db/migrations` — Alembic (single initial migration + `vn_normalize`
  SQL function + PostGIS extensions).
- `sources/` — YAML descriptors (`demo/demo-district-{v1,v2,docs}`) with
  declared `key_field: ma_loai_dat`.
- `fixtures/synthetic/demo_district` — generated GPKG/PDF/COG fixtures.
- `tests/unit` (80) — `tests/integration` (19, marker `integration`).
- `scripts/` — `generate_fixtures.py`, `seed_demo.py`, `export_openapi.py`.

## Conventions

- snake_case modules; connectors implement the `Connector` protocol.
- Public service functions take `Session` or open `session_scope()`.
- Env via `OQH_` prefix; secrets only in `.env` (gitignored).
- Errors: `OQHError` → `{"error": code, "message": …}`; unknown → 500
  `{"error":"internal_error"}`.
