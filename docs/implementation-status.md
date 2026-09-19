# Implementation Status — V1 + real-source infrastructure

State after the provenance-first real-data phase. Verification commands were
run in this repo (WSL: `.venv/bin/python3.14 -m pytest`, docker infra via
`wsl -u root docker`).

## Verified green

| Check | Result |
|---|---|
| `pytest tests` | 143 passed (~87s): unit + integration |
| Web `npm run typecheck` / `npm run build` | clean; static export |
| Alembic | `b7f2c41d9e10` (crawl state + metadata origin) applied |
| Live crawl: `qhkt-phe-duyet-quy-hoach` | 191 decision PDFs, ~609 MB, 0 errors |
| Live crawl: `stnmt-geoserver-wfs` | 5 typenames, 47.5 MB, 10,468 planning polygons + 22 boundaries |
| Live crawl: `stnmt-wcs-lidar` | 26 MB GeoTIFF → `official_raster`, pending review |
| Demo seed round-trip | v1+v2 ingest, docs, georef, publish, compare — all green |

## What shipped in this phase

**Source registry & crawl state**
- Descriptor schema v2: refresh policy, rate limits, crawl policy,
  canonical-URL rules, provenance/evidence block, `admin_codes`.
- `sources/` hierarchy: `_schema/`, `demo/` (synthetic), `vietnam/`
  (`national/`, `provinces/`). Key is identity; admin codes are GSO-verified.
- New tables: `source_resources`, `source_observations`,
  `source_crawl_state`, `source_change_events`; `metadata_origin` on
  `documents` + `planning_versions`.

**Fetch & discovery**
- `http_client`: conditional GET (ETag/Last-Modified → 304), sha256,
  expected-checksum validation, byte caps (content-length + streaming),
  429/5xx retry, post-redirect SSRF re-check, response-header capture.
- `robots`: per-origin robots.txt (1h cache), RFC 9309 group precedence,
  crawl-delay, 4xx-allow vs 401/403/5xx/transport-deny.
- New connectors: `sitemap` (+index), `feed` (RSS/Atom + enclosures),
  `ckan` (package_search), `ogc_api_features`; HTML pagination + filters;
  WFS/WMS typename filters.

**Crawl runner & scheduler**
- `sync_source`: per-source observation cycle — discovery → conditional
  fetch → content-addressed staging → dispatch; upstream change detection
  (added/disappeared/reappeared/checksum/url/metadata) with from/to
  artifact links; health + `next_check_at` + failure backoff.
- Scheduler: `due_sources` selection, enqueue locks, per-host concurrency,
  `sync_source` jobs on inline|Redis queue. CLI: `scheduler tick|loop`.

**Metadata provenance**
- `metadata_origin` levels (`official_explicit`, `derived_deterministic`,
  `derived_machine`, `human_reviewed`, `unknown`); weakest origin wins —
  machine candidates in `meta` count. Evidence-bearing PDF candidates
  (page/snippet/pattern), `field_origins`, `needs_ocr` → review tasks.
- Planning-version resolution accepts extraction hints; machine-extracted
  documents are review-gated.

**Assisted OCR (`openquyhoach_ingest.ocr`)**
- Offline adapter: `pdftoppm` (poppler) + `tesseract` with `vie`
  traineddata — no external service, no credentials.
- `ocr` CLI batch (`--limit/--dpi/--lang/--max-pages`); per-document
  `ocr_document()`; skips gracefully when binaries absent.
- OCR output lives on `document.meta['ocr']` (engine, lang, dpi, pages,
  text sha256 + capped preview, candidates with page/snippet evidence).
- Fields are filled **only when empty** and marked `derived_machine`;
  a metadata review task is ensured; provenance event records
  `tool=tesseract/<ver>` + params. Original scanned artifact untouched.

**Semantic vector dedup**
- `_vector_content_digest`: sha256 over sorted (layer, external id,
  class, properties, WKB) — stable across byte-level upstream re-renders
  (e.g. GeoServer regenerating identical GeoJSON).
- `_dedupe_semantic` runs after every vector ingest: identical content
  to the prior dataset of the same name/record drops the redundant copy
  (+ its empty version); the new artifact/observation stay as evidence.
  Verified live: 5 identical WFS re-ingests deduped, 2 genuinely new
  layers kept.

**Operational surfaces**
- API: `/v1/sources`, `/v1/sources/{key}`, `/v1/changes`, `/v1/coverage`
  (freshness-enriched), `/v1/coverage/detail`, record `data_class`.
- MCP read-only: `source_status`, `recent_changes`, `planning_versions`.
- CLI: `sources discover|sync|sync-all|status|failures`, `coverage`,
  `changes recent`, `scheduler tick|loop`.
- Web: sources tab (health/freshness/errors), REAL DATA/DEMO/MIXED badges,
  document origin badges, sources section in provenance drawer.

**Real pilots (verified, ingested)**
- `vietnam/provinces/ho-chi-minh/stnmt-geoserver-wfs` — official WFS
  planning polygons (VN-2000), 7 typenames (4 district QHPKSDD layers +
  QHPKSDD_SHAPE + 3 DGHC boundary layers); all published to PMTiles.
- `vietnam/provinces/ho-chi-minh/qhkt-phe-duyet-quy-hoach` — official
  HTML listing → 190+ scanned decision PDFs (needs_ocr + review tasks).
- `vietnam/provinces/ho-chi-minh/stnmt-wcs-lidar-vandai3-thuduc` — official
  WCS GeoTIFF (LiDAR orthophoto).
- `vietnam/provinces/ho-chi-minh/sqhkt-qlqh-portal` — official Sở QHKT
  portal API (`sqhkt_grid` connector): grid-samples `POST /api/doan/ranhqhpk`
  to enumerate every approved QHPK plan city-wide (no bulk list exists).
  ~129 plans → per-plan record + version (decision number/date at
  `derived_deterministic`), boundary dataset, official plan-map PDF —
  all published.

**Other provinces (verified, ingested)**

- `vietnam/provinces/ha-noi/vqh-van-ban-phap-luat` — Viện Quy hoạch xây
  dựng Hà Nội (.gov.vn) laws module: 215 official planning/legal PDFs
  (Luật QH đô thị, Luật Thủ đô, QĐ phê duyệt QHPK…) via html_index +
  path pagination; `download=1` links → PDF w/ Content-Disposition.
- `vietnam/provinces/ha-noi/quyhoach-hanoi-vn-zoning` — quyhoach.hanoi.vn
  lookup portal (vendor-operated, NOT .gov.vn): 3 zoning layers as
  `var x = {FeatureCollection}` JS files → new `jsvar_geojson` format
  (raw .js kept as immutable artifact, extraction at ingest). 45 phân-khu
  zones + master plan + 15 đô thị vệ tinh — honest level
  `derived_machine_unreviewed` (authority unverified) → review-gated.
- `vietnam/provinces/khanh-hoa/gis-khanhhoa-arcgis` — provincial ArcGIS
  REST: 30 layers across 12 MapServers (district QHSDD Nha Trang/Cam
  Ranh/Cam Lâm/Diên Khánh/Khánh Sơn, QH chung Nha Trang, Cam Ranh detail
  plans, KT3A zoning, admin boundaries) → official_vector, published.
- `vietnam/provinces/tay-ninh/gis-tayninh-geoserver-wfs` — provincial
  GeoServer WFS: 38 planning typenames (QHSDD cấp tỉnh + Long An district
  plans, sector plans, boundaries) → official_vector, published.
- `vietnam/provinces/hai-phong/quyhoach-haiphong-ekgis` — official
  `quyhoach.haiphong.gov.vn` eKGIS point-lookup (`new ekgis_grid`
  connector): grid-samples `LayThongTinQuyHoachTheoViTri` city-wide,
  dedupes plans by maHoSo/maLienKet, fetches authoritative detail via
  `LayThongTinDoAnTheoMa`. `verify_tls: false` — the gov IIS serves an
  incomplete cert chain (verified; documented in descriptor).
  **82 plans ingested (incl. former Hải Dương post-2025 merger), all
  82 versions published** — real titles/QĐ via planning_hints.
- `vietnam/provinces/hai-phong/data-haiphong-ckan` +
  `vietnam/provinces/can-tho/data-cantho-ckan` — official open-data
  CKAN catalogs; planning datasets (QHSDD land-use extracts XLSX/PDF).
- `vietnam/provinces/an-giang/sxd-quy-hoach-{phan-khu,kien-truc}` —
  Sở Xây dựng An Giang (.gov.vn, Drupal) announcement indexes →
  31 + 11 approval-decision PDFs via detail-page follow, 0 errors.
  Covers the post-2025 merged province incl. former Kiên Giang
  (Phú Quốc, Rạch Giá). `de-an-ttcb` section confirmed empty upstream
  (page renders "Không có" — not a connector bug).
- `vietnam/national/congbao-chinhphu-qd-ttg` — official national
  gazette QĐ-TTg index → signed decision PDFs on congbaocdn/
  g7.cdnchinhphu.vn. `title_include` restricts discovery to planning
  QĐs: **269 docs ingested incl. 60 "phê duyệt Quy hoạch tỉnh/thành
  phố" approvals (2022–2024 wave, tầm nhìn 2050)** — among them
  Hà Nam 1686/QĐ-TTg and Ninh Bình 218/QĐ-TTg, so both provinces now
  have their provincial plan as a signed official PDF even though
  their own portals are dead/auth-walled. `verify_tls: false` — CDN
  ships an incomplete cert chain (verified 2026-09-19).

**Connector/ingestor fixes from provincial expansion**

- `arcgis_rest`: `discovery.services` (multi-MapServer descriptors),
  layer-name include/exclude, `maxRecordCount`-aware page size,
  OBJECTID-range fallback for pre-10.3 servers without pagination
  (`supportsPagination:false`), `server_feature_count` audit field.
- `jsvar_geojson`: `var name = {FC}` container detection in
  `sniff_format` + extraction branch in `dispatch_artifact`.
- `_jsonb_safe`: NaN/Infinity floats in source properties → NULL
  (Postgres JSONB rejects the `NaN` token — crashed real Tây Ninh ingest).
- Z-dimension geometries forced to 2D for the canonical column
  (Z preserved losslessly in `source_geometry_ewkb`).
- `crawl_policy.verify_tls` — descriptor-scoped TLS opt-out threaded
  through robots, http_client, ckan, sitemap, feed, ogc_api, html
  (discovery + fetch), planning_portal, ekgis_grid, sqhkt_grid,
  arcgis_rest. For verified-official hosts whose IIS/CDN ships an
  incomplete certificate chain (quyhoach.haiphong, data.haiphong,
  g7.cdnchinhphu).
- file:// items honor `suggested_filename` for the fetch copy — random
  temp names previously leaked into dataset/layer names (82 Hải Phòng
  datasets renamed to `ekgis_{maHoSo}` post-hoc).
- html connector emits listing anchor text as `metadata.title` +
  `article_url`; `_ingest_pdf` prefers it over CDN filenames
  (110 congbao docs re-titled from "Q_-TTg.pdf" to real decision titles).
- robots.txt fetch retries transient transport errors (3 attempts,
  backoff) before deny-all — flaky gov IIS stalls no longer fail runs.
- html_index param/path pagination now yields the bare index page first —
  `start` previously skipped page 0/1 entirely (vqh +52 docs on re-sync).
- `ekgis_grid` connector: grid point-lookup enumeration for the eKGIS
  portal family; all-requests-failed sweeps raise instead of reporting
  a clean empty result.

**Tests added (39 new)**
- Unit: robots policies + UA-group precedence; http client (conditional,
  caps, checksum, retry, redirect/SSRF, UA); discovery connectors (sitemap,
  feed, ckan, ogc-api, html, wfs) via respx; pdfmeta candidates/needs_ocr.
- Integration: crawl state lifecycle (added/unchanged/disappeared/
  reappeared/checksum-revision), scheduler due/lock/backoff, health,
  document origin weakening + review tasks.

## Bug classes fixed in this phase

- Document origin ignored machine candidates in `meta` → weakest-origin
  now includes candidate data (9 live docs repaired).
- WFS temp-file names leaked into layer/dataset names →
  `suggested_filename` + `layer_map_aliases` fallback.
- `/v1/coverage` route shadowed by existing query route → freshness merged,
  detail moved to `/v1/coverage/detail`.
- respx tests hit SSRF DNS check → resolvable test hosts (example.com).

## Known limitations

- Scanned decision PDFs are `needs_ocr` — OCR pipeline is optional and not
  yet implemented (documents + provenance are stored regardless).
- Live WFS layers stay `pending` review; nothing publishes without approval.
- Scheduler runs on-demand/daemon in-process; no external cron wiring yet.
- Raster tiles still read the whole COG per request.
- No per-user auth; admin ops use the dev `X-Admin-Key`.

## Unresolved questions

- Redistribution terms for all real pilots are `unknown` —
  conservative metadata+provenance only until clarified.
- OCR batch for scanned PDFs is partially run (tesseract vie+eng);
  remaining scans still `needs_ocr`.
- Most provincial `.gov.vn` GIS hosts were unreachable from the dev
  network during discovery (geo-blocking/hosting); verified reachable +
  onboarded: TP.HCM, Hà Nội, Khánh Hòa, Tây Ninh, Hải Phòng, Cần Thơ,
  An Giang. Candidates found but not onboarded: gis.cantho.gov.vn (only
  sample services), gis.hatinh (SPA + token API), Đà Nẵng congdulieu.vn
  (ZK app — no REST API), qhkhsdd.hanoi.gov.vn (eKGIS parcels —
  metre-scale, not grid-enumerable), quyhoach.hanoi.gov.vn (official
  trial planning system — `/map/all/public` lists "QHSDĐ QHC 100 năm"
  but feature export + planning tiles are auth-walled/empty),
  congbao.{angiang,sonla,tayninh} (bound-issue gazette PDFs — need
  per-decision segmentation), opendata.angiang (downloads login-walled).
- Hà Nam: no usable provincial source — sxd.hanam.gov.vn deactivated
  (NotActive.htm), stnmt.hanam.gov.vn unreachable, hanam.gov.vn serves
  error shell. The provincial plan itself is covered via the national
  gazette source: QĐ 1686/QĐ-TTg (2023, tầm nhìn 2050) on
  congbao.chinhphu.vn.
- Ninh Bình: gis.ninhbinh auth-walled, sxd.ninhbinh internal-only,
  data.ninhbinh SPA with 404 API endpoints (partially deployed).
- Tây Ninh WFS `max_features: 8000` caps 3 large layers (qhsdd_duchoa,
  quyhoach1, A05_QuyHoachTaiNguyenNuoc) — raise cap or page server-side
  when full coverage needed.
