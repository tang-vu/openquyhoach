# OpenQuyHoach — Implementation Plan

> Working plan for V1. See `ROADMAP.md` for product stages and
> `docs/implementation-status.md` (generated at the end of the build) for what
> was actually delivered.

## North star

Every polygon must be able to answer: *"Where did you come from?"*

## Technology decisions

| Area | Choice | Rationale |
|---|---|---|
| API/worker language | Python 3.12+ (3.14 used in dev) | GDAL ecosystem, FastAPI |
| API framework | FastAPI + SQLAlchemy 2 + Alembic | boring, typed, well supported |
| DB | PostgreSQL 17 + PostGIS 3.5 | spatial indexes, ST_AsMVT |
| Object store | S3 API (MinIO local) | provider neutral |
| Queue | `JobQueue` protocol: inline + Redis list backend | swappable, no Celery magic |
| Web | Next.js (App Router) + React + MapLibre GL + TanStack Query | spec'd |
| Admin | protected `/admin` routes inside `apps/web` | one fewer app to operate; auth boundary identical |
| Vector tiles | PostGIS `ST_AsMVT` dynamic + PMTiles v3 writer (own impl) | no tippecanoe dependency |
| Raster tiles | rio-tiler reading COG from object storage | OSS standard approach |
| Package mgmt | uv workspace (`uv.lock`) + pnpm workspace (`pnpm-lock.yaml`) | lockfiles required |
| AI | provider interfaces, `AI_ENABLED=false` default | optional enhancement |

## Build order

1. **A. Bootstrap** — monorepo, licenses, env, compose, workspaces, CI skeleton.
2. **B. Domain model** — `openquyhoach_core` (settings, db, enums, all ORM models), Alembic migration.
3. **C. Geo** — `openquyhoach_geo`: CRS metadata capture (EPSG/WKT/PROJJSON), transform policy (never guess VN-2000), PMTiles v3 writer, COG helpers.
4. **D. Quality** — `openquyhoach_quality`: stable rule codes, geometry/attribute/temporal/provenance rules, JSON + human reports, CI exit codes.
5. **E. Ingestion** — `openquyhoach_ingest`: source registry (YAML + JSON Schema), connector protocol (`discover/fetch/inspect/normalize/emit`), connectors: file, http, html, arcgis_rest, ogc (WMS meta + WFS), vector, raster, pdf, planning_portal (conservative). Pipeline: DISCOVER→FETCH→CONTENT-ADDRESS→DETECT→METADATA→CRS→VALIDATE→NORMALIZE→PROVENANCE→REVIEW-GATE→PUBLISH, idempotent.
6. **F. CLI** — `openquyhoach` (doctor, sources, ingest, validate, publish, compare, db).
7. **G. API** — `apps/api`: `/api/v1` endpoints, point/bbox query with provenance summary, MVT tiles, raster tiles, manifests, ETag, pagination, rate guards.
8. **H. Worker** — `apps/worker`: queue consumer + inline runner sharing the same pipeline functions.
9. **I. Fixtures/seed** — synthetic **DemoDistrict**: GPKG (2 versions), approval PDF, raster scan + COG, admin unit, provenance, one quality issue.
10. **J. Web** — map-first UI (vi default), layer panel, timeline, inspect drawer with provenance, compare view, admin (runs, review queue, georef, publish).
11. **K. Georeferencing** — GCP CRUD, affine/2nd-order/TPS-where-justified solvers, RMSE/residuals, RANSAC rejection, review gate.
12. **L. MCP** — `openquyhoach_mcp` experimental read-only tools.
13. **M. Tests** — unit + integration + fixture-based connector tests + Playwright smoke.
14. **N. Docs** — all spec'd documents + ADRs.
15. **O. Clean-room verification** — documented commands from scratch.

## Deferred consciously (documented in implementation-status.md)

- Kubernetes, Elasticsearch, Kafka — explicitly out of scope.
- DWG decoding — detect-and-direct-to-DXF conversion path only.
- Production OIDC — auth abstraction + dev token provider only.
- Manifest signing — format designed, signing deferred.
