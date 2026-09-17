# Implementation Status — V1

State at end of the autonomous build. Verification commands below were all
run in this repo.

## Verified green

| Check | Result |
|---|---|
| `make test` | 99 passed (80 unit + 19 integration), ~63s |
| `make lint` (ruff) | clean |
| `make typecheck` (mypy) | clean, 78 files |
| `pnpm --filter @openquyhoach/web typecheck` / `build` | clean; static export in `apps/web/out` |
| Alembic downgrade→upgrade | clean round-trip, 19 domain tables |
| CLI | `doctor`, `sources validate` (3 descriptors, 0 issues) |
| Redis/Valkey queue | enqueue → worker consume → failed=0 |
| MCP server | 4 tools registered |
| API live check | search, point-query, records, versions, datasets, publications, manifest, MVT tiles — 200s with real data |
| Demo seed | v1+v2 ingest, docs ingest, georef RANSAC rejects planted outlier, 2 PMTiles publications (30 tiles each), changeset (1 added, 3 geom-changed, 3 prop-changed), coverage row |

## What shipped vs plan

- Web UI is a **static export** (not the spec'd SSR + TanStack Query) —
  simpler to host, still fully functional. No Playwright e2e yet.
- Admin is a tab in the web app (dev-token `X-Admin-Key`), not a separate
  `/admin` route tree.
- MCP is a stdio-style package exposing 4 read-only tools.
- Manifest signing: format supports it; signing deferred.
- DWG: detect-and-redirect only.

## Bug classes fixed during build (selected)

- Empty rule registry (`run_rules` never imported rule modules).
- `build_tiles` chicken-and-egg `published` filter → zero-tile PMTiles.
- Georef RANSAC swallowed by collinear affine subset → rank check +
  scale-derived threshold.
- Changesets all add/remove until `key_field: ma_loai_dat` declared +
  pyogrio property extraction fixed.
- `FetchResult` losing `suggested_filename`; ndarray truthiness bugs;
  `BeautifulSoup` multi-valued `href` typing; FastAPI 0.141 lazy routers
  (`app.setup()`); `TileOutsideBounds`→404; `secrets.compare_digest` admin.

## Known limitations / deferred

- Real-source onboarding untested against live portals (connectors are
  conservative; robots/legal review required per source).
- No per-user auth, rate limiting is minimal (bbox size guard only).
- Raster tiles read the whole COG object per request (fine at demo scale;
  use presigned-range serving at volume).
- Under WSL2/DrvFs, Node dev servers can stall — use `make web-serve`.

## Unresolved questions

- Which province/portal should be the first real source pilot?
- Desired retention policy for `ingestion_runs` and rejected artifacts?
- Should publications support per-layer min/max zoom in the manifest?
