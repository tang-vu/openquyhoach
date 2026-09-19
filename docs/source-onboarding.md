# Source Onboarding

How a real Vietnamese planning source becomes a tracked, versioned,
provenance-bearing part of OpenQuyHoach.

## The rule

> **Verify before you describe. Describe before you crawl.**
> Never fabricate a source URL, an authority name, or a decision number.
> If you cannot show the source is legitimately public, it does not go in.

## 1. Verify the source (before writing any YAML)

For every candidate source, establish and record:

- **Authority** — which government body publishes it (Sở TN&MT, UBND,
  ministry portal, GeoServer under a gov.vn domain, …). Prefer the
  authority's own domain; verify the DNS/domain is genuinely theirs.
- **Official status** — why it counts as an official source (statutory
  publication duty, open-data decree, linked from the authority's portal).
  Record supporting URLs in `provenance.evidence`.
- **Access legality** — it is publicly reachable without login, CAPTCHA,
  paywall, or technical access control. Check `robots.txt`; note the result
  in `robots`/`notes`. If robots disallow crawling, do not crawl.
- **Redistribution** — what the license/terms say. When unclear, set
  `rights.redistribution_status: restricted` or `unknown` and keep
  publication conservative (metadata + provenance, no republished bytes).
- **Shape** — actually probe the endpoints (WFS GetCapabilities, sitemap,
  listing page, CKAN action API) and record what you saw.

## 2. Descriptor authoring

Descriptors live under `sources/` in a stable hierarchy:

```
sources/
  _schema/                  JSON Schema for descriptors
  demo/                     synthetic fixtures — deterministic CI data only
  vietnam/
    national/               ministry-level sources
    provinces/<province>/   provincial authority sources
```

The **key is identity** (`vietnam/provinces/ho-chi-minh/stnmt-geoserver-wfs`).
Administrative reorganisation changes `jurisdiction`/`admin_codes`, never
the key. `demo/*` keys are reserved for synthetic fixtures — data from them
is labelled `synthetic` end-to-end and must never look real.

Minimal skeleton (every block documented in `sources/_schema/source-descriptor.schema.json`):

```yaml
key: vietnam/provinces/ho-chi-minh/example-portal
name: "Sở TN&MT TP.HCM — example listing"
description: >
  What this source publishes and why it is official.
authority: "Sở Tài nguyên và Môi trường TP.HCM"
jurisdiction: "Thành phố Hồ Chí Minh"
admin_codes:
  province: "79"            # GSO codes only — verified, never invented
source_type: html           # file | http | html | sitemap | feed | ckan |
                            # ogc_api_features | arcgis_rest | ogc_wfs |
                            # ogc_wms | planning_portal
base_url: "https://example.hochiminhcity.gov.vn/listing.html"
discovery:
  follow: "a.download"      # connector-specific options — see §3
refresh:
  interval_seconds: 604800  # weekly
  jitter_seconds: 3600
rate_limit:
  requests_per_minute: 20
  concurrent_requests: 1
crawl_policy:
  respect_robots: true
  user_agent: null          # defaults to the OpenQuyHoach UA
parser:
  default_dataset_group: quy_hoach
planning:
  planning_type: quy_hoach_phan_khu
rights:
  license: "see terms"
  rights_statement: "Public government information; verify terms."
  redistribution_status: unknown
provenance:
  evidence:
    - "https://example.hochiminhcity.gov.vn/about.html"
  verification_date: "2026-09-01"
enabled: true
priority: 100
```

Mutable runtime state (last check, health, failures) lives in the database —
**never** in committed YAML.

Validate: `openquyhoach sources validate`.

## 3. Discovery options per connector

| `source_type` | Finds resources via | Key `discovery:` options |
|---|---|---|
| `file` | local dir globs | `path`, `globs` |
| `http` | explicit URL list | `urls`, optional `filename` |
| `html` | links on a listing page | `follow`/`detail` (CSS selector), `include`, `exclude` (URL regex or list, applied to the listing link), `title_include`, `title_exclude` (anchor-text regex — skips detail fetches), `pagination` (`style: param|path|next_link`, `param`, `path_template`, `next_link`, `max_pages`), `max_resources` |
| `sitemap` | sitemap.xml + sitemap indexes | `url`, `include`/`exclude`, `max_resources` |
| `feed` | RSS/Atom items + enclosures | `url`, `allowed_formats`, `include`/`exclude`, `max_resources` |
| `ckan` | `package_search` + resource URLs | `base`, `package_query`, `fq`, `organization`, `row_limit`, `allowed_formats`, `max_resources` |
| `ogc_api_features` | `/collections` (+ `/items` links) | `base`, `include`/`exclude`, `collections`, `max_resources` |
| `ogc_wfs` | GetCapabilities typenames | `base`, `include`/`exclude` (typename regex), `max_resources` |
| `ogc_wms` | GetCapabilities layers | `base`, `include`/`exclude` |
| `arcgis_rest` | Feature/MapServer layer list | `base` or `services` (multi-service), `include`/`exclude` (layer-name regex), `max_resources` |
| `sqhkt_grid` | TP.HCM portal point-lookup sweep | `bbox`, `step`, `delay` |
| `ekgis_grid` | eKGIS portal point-lookup sweep (Hải Phòng et al.) | `lookup_url`, `detail_url`, `bbox`, `step`, `delay` |
| `planning_portal` | portal-specific paging | portal-dependent |

`include`/`exclude` accept a single regex or a list; resources matching an
exclude are dropped, then (when include is present) must match include.

**ArcGIS legacy servers**: `arcgis_rest` pages with `resultOffset` by
default and falls back to OBJECTID-range queries on pre-10.3 services
("Pagination is not supported"), degrading `orderByFields` /
`resultRecordCount` independently. `discovery.services` lets one
descriptor cover multiple MapServers.

**JavaScript-wrapped GeoJSON** (`jsvar_geojson`): portals that publish
layers as `var name = {FeatureCollection};` (e.g. quyhoach.hanoi.vn) are
fetched with the `http` connector — the raw `.js` stays the immutable
artifact, the payload is validated+extracted at ingest. Vendor-hosted
content of this kind is `derived_machine_unreviewed`, never official.

**TLS**: `crawl_policy.verify_tls: false` disables certificate
verification for a single source — descriptor-scoped, never global.
Use only for verified government/vendor hosts whose IIS/CDN ships an
incomplete certificate chain (observed on `*.haiphong.gov.vn` and
`g7.cdnchinhphu.vn`); document the verification date in `provenance`.

## 4. Run it

```bash
openquyhoach sources sync <key>          # discover → fetch → stage → ingest
openquyhoach sources discover <key>      # dry discovery listing only
openquyhoach sources status [<key>]      # health + freshness
openquyhoach changes recent              # upstream change events
```

First sync creates `source_resources`, `source_observations`,
`source_artifacts` (immutable, sha256-addressed), `provenance_events`,
plus documents/datasets routed to a planning version. Subsequent syncs
record `seen_unchanged` / `seen_changed` / `not_modified` /
`disappeared` / `reappeared` and emit `source_change_events`.

## 5. Review obligations

- A scan PDF → `needs_ocr` evidence + review task (OCR is optional, always
  derived).
- Regex-extracted decision fields → `derived_machine` origin + review task.
- CRS uncertainty → review task, never a silent guess.
- Unclear rights → keep `redistribution_status` conservative; metadata and
  provenance are stored, republication stays off.

## 6. Pilot sources (verified, live)

| Descriptor | Shape | Authority |
|---|---|---|
| `vietnam/provinces/ho-chi-minh/stnmt-geoserver-wfs` | WFS planning polygons (VN-2000) | Sở TN&MT TP.HCM GeoServer |
| `vietnam/provinces/ho-chi-minh/qhkt-phe-duyet-quy-hoach` | HTML listing → 190+ decision PDFs | Trung tâm QHKT TP.HCM |
| `vietnam/provinces/ho-chi-minh/stnmt-wcs-lidar-vandai3-thuduc` | WCS GeoTIFF (LiDAR orthophoto) | Sở TN&MT TP.HCM GeoServer |
| `vietnam/provinces/ho-chi-minh/sqhkt-qlqh-portal` | `sqhkt_grid` sweep → plan boundaries + decision PDFs | Sở QHKT TP.HCM portal API |
| `vietnam/provinces/ha-noi/vqh-van-ban-phap-luat` | HTML laws module → 215 legal PDFs | Viện QH xây dựng Hà Nội (.gov.vn) |
| `vietnam/provinces/ha-noi/quyhoach-hanoi-vn-zoning` | `jsvar_geojson` zoning layers | vendor portal — **derived_machine_unreviewed** |
| `vietnam/provinces/khanh-hoa/gis-khanhhoa-arcgis` | 30 layers / 12 MapServers | Sở TN&MT Khánh Hòa ArcGIS |
| `vietnam/provinces/tay-ninh/gis-tayninh-geoserver-wfs` | 38 WFS typenames | Tỉnh Tây Ninh GeoServer |
| `vietnam/provinces/hai-phong/quyhoach-haiphong-ekgis` | `ekgis_grid` sweep → 82 plan boundaries+details | Sở Xây dựng Hải Phòng eKGIS |
| `vietnam/provinces/hai-phong/data-haiphong-ckan` | CKAN catalog → planning XLSX | Cổng dữ liệu Hải Phòng |
| `vietnam/provinces/can-tho/data-cantho-ckan` | CKAN catalog → planning XLSX/TXT | Cổng dữ liệu Cần Thơ |
| `vietnam/provinces/an-giang/sxd-quy-hoach-{phan-khu,kien-truc}` | HTML index → 42 decision PDFs | Sở Xây dựng An Giang |
| `vietnam/national/congbao-chinhphu-qd-ttg` | QĐ-TTg index → signed decision PDFs | Văn phòng Chính phủ — Công báo |
