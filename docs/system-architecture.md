# System Architecture

## Overview

```
sources (file/http/html/arcgis/ogc/portal/pdf/raster)
   │  discover → fetch (SSRF-guarded)
   ▼
openquyhoach_ingest.pipeline
   │  content-address → detect → metadata → CRS → validate →
   │  normalize → provenance → review-gate
   ▼
PostGIS ────────────────┐        MinIO / S3 (content-addressed artifacts,
 │ domain tables        │         PMTiles, manifests)
 │ provenance_events    │
 │ quality_observations │
 │ review_tasks         │
 ▼                      │
openquyhoach_services  ─┘  publish → PMTiles + manifest → object store
   │  search / point-query / provenance / compare / coverage
   ▼
FastAPI (/v1/*)  ──→  apps/web (Next.js static export + MapLibre)
   │                    MVT tiles, raster PNG tiles, manifests
   └─→ openquyhoach_mcp (read-only tools for agents)
   └─→ apps/worker (inline | Redis queue)
```

## Layers

**Domain (`openquyhoach_core`)** — settings, SQLAlchemy 2 models, object
storage abstraction (`artifact_store` / `published_store`), queue protocol
(`inline` / `redis`), provenance event writer, SSRF/URL guard, hashing.
PostGIS holds: `sources`, `source_artifacts`, `planning_records`,
`planning_versions`, `datasets`, `layers`, `features`, `documents`,
`ingestion_runs`, `quality_observations`, `review_tasks`,
`georeference_jobs`, `change_sets`/`change_set_entries`, `publications`,
`provenance_events`, `coverage_summaries`, `authorities`,
`administrative_units`.

**Geo (`openquyhoach_geo`)** — CRS capture (EPSG/WKT/PROJJSON) with
VN-2000 detection via base-geodetic-CRS (EPSG:4756), explicit transform
policy (never silently guess VN-2000 zones), pyogrio vector IO, rasterio COG
helpers, `ST_AsMVT` tile SQL, PMTiles v3 writer/reader (Hilbert ids, varint
directory, leaf directories, duplicate-tile rejection), georeferencing
(affine / TPS with embedded anchors, RANSAC with degeneracy checks and
scale-derived rejection thresholds).

**Quality (`openquyhoach_quality`)** — registry of rules under stable
`QH-*` codes (geometry validity/type/collection/duplicates, CRS
missing/out-of-bounds, topology overlap/gap/cross, required attributes,
temporal order, artifact hash, orphan provenance, missing authority).
`run_rules` lazily imports rule modules; findings carry evidence, severity,
and target refs.

**Ingest (`openquyhoach_ingest`)** — connector protocol
(`discover/fetch/inspect/normalize/emit`), source descriptors validated by
JSON Schema, safe archive extraction (path traversal, member count,
expansion and compression-ratio limits), magic-byte + extension sniffing,
conservative PDF metadata extraction on `vn_normalize`d text, per-layer
`key_field` for stable cross-version matching, review-task creation for
un-georeferenced rasters.

**Services (`openquyhoach_services`)** — publish (review gate → MVT build →
PMTiles → manifest → flag), compare (stable-key matching, m² deltas via
geodesic area), search (folded-diacritics + coordinate parsing), provenance
(summary chains + event DAG), coverage.

**Interfaces** — FastAPI (`/v1/*`, admin token via `secrets.compare_digest`,
`PageDep` pagination), CLI (Typer/Rich), worker (inline or Redis list
queue), MCP (4 read-only tools), web (static-exported Next.js + MapLibre).

## Data invariants

- Artifacts are immutable and content-addressed; storage keys are derived
  from sha256.
- `planning_versions` are never destructively updated; amendments create
  new versions linked via `supersedes_version_id`.
- `derivation_level` distinguishes `official_vector` / `official_raster` /
  documents / `derived_*` levels; `review_status` gates publication.
- Publication manifests embed source list, artifact sha256s, checksums and
  a legal disclaimer; the PMTiles archive is itself content-addressed.
