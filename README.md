# OpenQuyHoach

**Open, verifiable planning-data infrastructure for Vietnam.**

OpenQuyHoach turns fragmented public planning documents and geospatial
datasets (quy hoạch sử dụng đất, quy hoạch phân khu, bản đồ địa chính scans,
…) into **structured, versioned, traceable, queryable** geospatial
information — while always preserving provenance and the distinction between
official source material and derived data.

> **Legal disclaimer:** OpenQuyHoach is an interoperability and transparency
> layer. It does **not** certify the legal validity of any plan. Geometric
> differences between versions are not legal interpretations. Always confirm
> with the responsible authority (Sở TN&MT, UBND, …) before acting.

## The invariant

> Every answer must be traceable back to evidence. Every geometry must know
> where it came from. Every transformation must be explainable. Every
> planning version must remain historically recoverable.

## What's inside

| Path | What |
|---|---|
| `python/openquyhoach_core` | Settings, ORM domain model, storage (S3/local), queue, provenance, SSRF guard |
| `python/openquyhoach_geo` | CRS registry (incl. VN-2000 detection), vector/raster IO, PMTiles v3 writer/reader, georeferencing (affine/TPS + RANSAC) |
| `python/openquyhoach_quality` | Validation engine with stable rule codes (`QH-*`) |
| `python/openquyhoach_ingest` | Connector protocol + file/http/html/arcgis/ogc/vector/raster/pdf connectors, staged pipeline |
| `python/openquyhoach_services` | Publish (PMTiles+manifest), compare/changesets, search, provenance, coverage |
| `python/openquyhoach_cli` | `openquyhoach` CLI — doctor, sources, ingest, validate, publish, compare, db |
| `python/openquyhoach_mcp` | Experimental read-only MCP tools (search, point query, provenance, coverage) |
| `apps/api` | FastAPI — `/v1/*` REST, MVT + raster tiles, publication manifests |
| `apps/worker` | Queue worker (inline or Redis/Valkey backend) |
| `apps/web` | Next.js + MapLibre UI — map, search, provenance drawer, compare, review admin |
| `db/` | Alembic migrations + `vn_normalize` SQL function |
| `fixtures/synthetic/demo_district` | Synthetic demo (GPKG v1/v2, PDFs, raster scan) — **no real-world meaning** |
| `sources/` | Source registry descriptors (YAML, JSON-Schema validated) |

## Quick start

Prereqs: Docker, Python 3.12+, Node 20+, pnpm, uv.

```bash
cp .env.example .env          # defaults work out of the box
make setup                    # uv sync --all-packages + pnpm install
make infra                    # PostGIS + MinIO + Valkey via docker compose
make migrate                  # alembic upgrade head
make seed                     # ingest + publish synthetic DemoDistrict

make api                      # FastAPI on :8000
make web-serve                # static build of apps/web on :3100
# or for development: make web  (next dev on :3100)
```

Then open http://localhost:3100 — click the map to query planned land use at
a point; every hit shows its provenance chain (source artifact sha256,
decision number, legal status).

```bash
make test                     # 80 unit + 19 integration tests
make doctor                   # env health check
make sources-validate         # validate source descriptors
make openapi                  # export docs/openapi.json
```

## Key properties

- **Immutable sources** — artifacts are content-addressed (sha256); identical
  bytes are never duplicated, originals never overwritten.
- **Versioned plans** — every planning version is preserved; changesets
  (`/v1/compare`) diff layers across versions with m² deltas and matched
  stable keys.
- **Review gates** — derived/georeferenced data cannot publish without human
  approval (`review_tasks` + `X-Admin-Key`), unless `allow_unreviewed` is
  explicitly passed.
- **Quality with evidence** — `QH-*` rule codes, severity, and target
  references on every finding.
- **Provenance everywhere** — point-query results carry dataset → artifact
  → source chains; publications embed a signed-shape manifest with source
  list, checksums, and a legal disclaimer.
- **Provider-neutral** — S3 API, any Redis-compatible queue, no proprietary
  AI required. AI assist is optional and off by default.

## API surface (selected)

```
GET  /v1/search?q=…                        records, units, docs, coordinates
GET  /v1/features/query?lon=&lat=          point query + provenance
GET  /v1/planning-records[/{id}]           records + versions
GET  /v1/planning-versions/{id}            version + datasets + publications
GET  /v1/versions/{id}/extent              bbox for framing
GET  /v1/publications[/{id}]               publication list/detail
GET  /v1/publications/{id}/manifest.json   provenance manifest
GET  /v1/publications/{id}/tiles/{z}/{x}/{y}.pbf   PMTiles-backed MVT
GET  /v1/tiles/{z}/{x}/{y}.pbf             live MVT over published data
GET  /v1/rasters/{dataset_id}/tiles/{z}/{x}/{y}.png  COG raster tiles
GET  /v1/compare?from_layer=&to_layer=     changeset between layer versions
GET  /v1/provenance/{type}/{id}            event graph
GET  /v1/coverage                          per-unit coverage summary
GET  /v1/review/tasks                      review queue
POST /v1/review/tasks/{id}/resolve         approve/dismiss (X-Admin-Key)
POST /v1/publish                           publish a version (X-Admin-Key)
POST /v1/sources/sync                      run ingestion (X-Admin-Key)
```

Mutating endpoints require `X-Admin-Key` (dev token: `OQH_ADMIN_TOKEN`).

## Docs

- `docs/system-architecture.md` — component diagram + data flow
- `docs/deployment-guide.md` — local + production notes
- `docs/codebase-summary.md` — module map
- `docs/code-standards.md` — conventions
- `docs/project-roadmap.md` — what's next
- `docs/implementation-status.md` — what V1 actually shipped
- `docs/implementation-plan.md` — original build plan

## License

MIT (see `LICENSE`). Fixture data is synthetic, CC0, and carries no
real-world planning meaning.
