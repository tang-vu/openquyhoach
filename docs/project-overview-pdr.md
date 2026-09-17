# Project Overview (PDR)

## Problem

Vietnamese planning data (quy hoạch) is published as scattered PDFs, scanned
maps, shapefiles/GeoPackages and portal listings across many authorities.
There is no open, versioned, provenance-preserving layer that lets citizens,
GIS systems, developers and future AI agents ask *"what is planned at this
point, and where does that answer come from?"*

## Product

**OpenQuyHoach** — an open interoperability layer between Vietnamese
planning source material, GIS systems, public map interfaces, developers
and AI agents.

Not a map demo: a data-infrastructure product whose core asset is
*trustable lineage*.

## Requirements delivered in V1

| Requirement | Where |
|---|---|
| Immutable source artifacts (sha256, filename, URL, retrieved_at, MIME, format) | `source_artifacts`, `storage.py` |
| Historical planning versions, never overwritten | `planning_versions`, `supersedes_version_id` |
| Official vs derived distinction | `datasets.derivation_level`, `review_status` |
| Human review gate before publishing derived/georef data | `review_tasks`, publish gate |
| Explainable quality findings | `QH-*` rules + `quality_observations` |
| Reproducible transformations | artifact + code + config + review decisions |
| Query: search, point, coverage | `/v1/search`, `/v1/features/query`, `/v1/coverage` |
| Compare versions | `/v1/compare`, `change_sets` |
| Serve: MVT (live + PMTiles), raster PNG, manifests | publish router |
| Interfaces: API, CLI, web, worker, MCP | apps/*, python/* |
| SSRF + archive safety | `security.py`, `archive.py` |
| No proprietary AI required | `AI_ENABLED=false` default |

## Users

- Citizens/journalists checking a parcel's planning status with evidence.
- GIS practitioners needing versioned, provenance-stamped layers.
- Developers via REST/MVT/PMTiles/MCP.
- Authorities reviewing automated extraction before publication.

## Non-goals (V1)

- Certifying legal validity (we surface provenance, not verdicts).
- Real authority workflows/OIDC (dev admin token only).
- Kubernetes/Elasticsearch/Kafka.
- DWG parsing (detect → direct to DXF path).
