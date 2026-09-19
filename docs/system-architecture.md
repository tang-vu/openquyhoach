# System Architecture

## Overview

```
sources (file/http/html/sitemap/feed/ckan/ogc-api/arcgis/ogc/portal)
   │  discover → fetch (SSRF-guarded, robots-aware, conditional GET)
   ▼
openquyhoach_ingest.crawl — observation cycle per source
   │  sync_source: upsert source_resources, append source_observations,
   │  emit source_change_events, refresh source_crawl_state (health,
   │  next_check_at); scheduler picks due sources (per-host concurrency,
   │  enqueue locks, failure backoff)
   ▼
openquyhoach_ingest.pipeline
   │  content-address → detect → metadata (origin-aware) → CRS →
   │  validate → normalize → provenance → review-gate
   ▼
PostGIS ────────────────┐      MinIO / S3 (content-addressed artifacts,
 │ domain tables        │       PMTiles, manifests)
 │ provenance_events    │
 │ quality_observations │
 │ review_tasks         │
 │ source_resources /   │
 │ source_observations /│
 │ source_crawl_state / │
 │ source_change_events │
 ▼                      │
openquyhoach_services  ─┘  publish → PMTiles + manifest → object store
   │  search / point-query / provenance / compare / coverage+freshness
   ▼
FastAPI (/v1/*)  ──→  apps/web (Next.js static export + MapLibre)
   │                    MVT tiles, raster PNG tiles, manifests,
   │                    sources/health tab, REAL-vs-DEMO badges
   └─→ openquyhoach_mcp (read-only tools: search, point query,
                        provenance, coverage, source_status,
                        recent_changes, planning_versions)
   └─→ apps/worker (inline | Redis queue; sync_source + scheduler jobs)
```

## Layers

**Domain (`openquyhoach_core`)** — settings, SQLAlchemy 2 models, object
storage abstraction (`artifact_store` / `published_store`), queue protocol
(`inline` / `redis`), provenance event writer, SSRF/URL guard, hashing,
robots.txt policy (RFC 9309 group selection, crawl-delay, origin cache).
PostGIS holds: `sources`, `source_artifacts`, `planning_records`,
`planning_versions`, `datasets`, `layers`, `features`, `documents`,
`ingestion_runs`, `quality_observations`, `review_tasks`,
`georeference_jobs`, `change_sets`/`change_set_entries`, `publications`,
`provenance_events`, `coverage_summaries`, `authorities`,
`administrative_units`, plus the crawl-state tables
(`source_resources`, `source_observations`, `source_crawl_state`,
`source_change_events`) and `metadata_origin`/`field_origins` provenance
on documents and versions.

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
(`discover`/`fetch`) with 11 connectors (file, http, html, sitemap, feed,
ckan, ogc_api_features, arcgis_rest, ogc_wfs, ogc_wms, planning_portal),
JSON-Schema-validated descriptors, hardened fetching (conditional requests,
redirect+SSRF re-validation, byte caps, checksums, retry/backoff, per-host
rate limiting), safe archive extraction, evidence-bearing PDF extraction on
`vn_normalize`d text (candidates + field origins + needs_ocr), the crawl
runner (`sync_source`) with upstream change detection, and the scheduler
(due selection, locks, host concurrency, failure backoff).

**Services (`openquyhoach_services`)** — publish (review gate → MVT build →
PMTiles → manifest → flag), compare (stable-key matching, m² deltas via
geodesic area), search (folded-diacritics + coordinate parsing), provenance
(summary chains + event DAG), coverage.

**Interfaces** — FastAPI (`/v1/*`, admin token via `secrets.compare_digest`,
`PageDep` pagination; ops router for sources/changes/coverage detail), CLI
(Typer/Rich — sources discover/sync/status/failures, coverage, changes,
scheduler), worker (inline or Redis list queue), MCP (read-only tools),
web (static-exported Next.js + MapLibre — sources/health tab, real-vs-demo
badges, origin badges on documents).

## Data invariants

- Artifacts are immutable and content-addressed; storage keys are derived
  from sha256; changed upstream bytes produce a *new* artifact revision —
  originals are never overwritten.
- `planning_versions` are never destructively updated; amendments create
  new versions linked via `supersedes_version_id`.
- `derivation_level` distinguishes `official_vector` / `official_raster` /
  documents / `derived_*` levels; `review_status` gates publication.
- `metadata_origin` (`official_explicit` / `derived_deterministic` /
  `derived_machine` / `human_reviewed` / `unknown`) records where each
  record's metadata came from; the weakest origin wins, and machine
  extraction always opens a review task.
- `data_class` (synthetic/official/mixed/unknown) classifies records and
  sources by the demo-vs-real origin of their backing artifacts — synthetic
  fixtures never look real.
- Upstream changes are first-class: `source_change_events` link resources,
  runs, and from/to artifact revisions; spatial diffs between versions live
  in `change_sets`/`change_set_entries`.
- Publication manifests embed source list, artifact sha256s, checksums and
  a legal disclaimer; the PMTiles archive is itself content-addressed.
