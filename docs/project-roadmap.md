# Project Roadmap

## V1 — shipped (see implementation-status.md)

- Domain model + PostGIS schema + Alembic migrations.
- Ingestion: 9 connectors, safe fetch/extract, content-addressed artifacts,
  PDF metadata extraction (folded-diacritics tolerant), raster georef path.
- Quality engine with `QH-*` stable rule codes.
- Publication: review gate → MVT → PMTiles + manifest → published flag.
- Services: search, point query+provenance, compare/changesets, coverage.
- API (34 routes), CLI, worker (inline|Redis), MCP (4 tools), web UI.
- Synthetic DemoDistrict fixtures + seed; 99 tests green; lint+mypy clean.

## V1.x hardening

- Playwright e2e smoke (map renders, point query, compare) — `test:e2e`
  target reserved.
- Generated TS SDK from `docs/openapi.json` (`make openapi` already
  exports the schema).
- Web: publication manifest view, document list/download, raster layer
  toggle (endpoint exists), coverage map layer, i18n (vi default).
- Streaming/large-archive handling; resumable fetch.

## V2 candidates

- Manifest signing (format already designed for it) + verification CLI.
- OIDC auth + per-authority roles; audit log for review decisions.
- Real-source onboarding playbook (province planning portals, NSPI,
  địa chính scans) with per-source legal/robots review.
- OGC API Features exposure; STAC catalog for raster artifacts.
- AI assist (optional): OCR for scanned quyết định, entity extraction —
  always into `derived_*` + review queue, never auto-published.
- Tile caching/CDN headers; PMTiles served directly by range-capable
  static host.
- DWG→DXF conversion pipeline.
