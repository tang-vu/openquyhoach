# Project Roadmap

## V1 — shipped (see implementation-status.md)

- Domain model + PostGIS schema + Alembic migrations.
- Ingestion connectors, safe fetch/extract, content-addressed artifacts,
  PDF metadata extraction, raster georef path.
- Quality engine with `QH-*` stable rule codes.
- Publication: review gate → MVT → PMTiles + manifest → published flag.
- Services: search, point query+provenance, compare/changesets, coverage.
- API, CLI, worker, MCP, web UI; synthetic DemoDistrict fixtures.

## V1.5 — real-source infrastructure (shipped)

- Source registry v2 (hierarchy, refresh/rate-limit/crawl-policy,
  provenance evidence, admin codes) + crawl-state tables.
- Hardened fetching: conditional GET, robots policy, SSRF re-check on
  redirects, byte caps, checksums, retries, per-host rate limits.
- New discovery connectors: sitemap, RSS/Atom, CKAN, OGC API Features;
  HTML pagination/filters; WFS typename filters.
- `sync_source` crawl runner: upstream change detection
  (added/disappeared/reappeared/checksum/url/metadata), persistent
  resources/observations, source health + freshness, scheduler with
  enqueue locks + failure backoff.
- Metadata provenance: `metadata_origin` levels + field origins +
  evidence-bearing PDF candidates + review tasks; weakest origin wins.
- Operational surfaces: `/v1/sources`, `/v1/changes`, coverage freshness,
  MCP source/changes/versions tools, CLI sources/coverage/changes/
  scheduler commands.
- Web: sources/health tab, REAL-vs-DEMO badges, origin badges.
- Three verified TP.HCM pilot sources ingested end-to-end (WFS polygons,
  HTML/PDF decisions, WCS raster).
- 143 tests green (39 new for crawl/http/robots/connectors/metadata).

## V2 candidates — next up

- **Offline OCR adapter** for `needs_ocr` scans (tesseract class) —
  OCR text always lands `derived_machine` + review, original preserved.
- **Broader source coverage** — more provincial GeoServers, ministry
  portals, data.gov.vn scrape; per-source legal review first.
- **Review workflow UI** — richer evidence display (PDF snippets/page
  images) for faster human confirmation of machine candidates.
- **OCR/AI assist (optional)** — entity extraction into `derived_*` +
  review queue, never auto-published.
- **Scheduler productionization** — daemon deployment, dead-letter
  handling, metrics export.
- **Playwright e2e** — map render, point query, compare, sources tab.
- **Manifest signing** + verification CLI (format already designed).
- **Per-layer zoom policy** in publication manifests.
- **OIDC auth + per-authority roles**; audit log for review decisions.
- **OGC API Features exposure**; STAC catalog for raster artifacts.
- **Tile caching/CDN headers**; range-capable PMTiles hosting.
- **DWG→DXF conversion pipeline**.
