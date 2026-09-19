# Data Provenance & Legal Posture

How OpenQuyHoach keeps every answer traceable to official evidence — and
what it does *not* claim.

## The invariants (non-negotiable)

1. Original evidence is immutable — artifacts are content-addressed
   (sha256) objects; never overwritten, never deleted.
2. Every derived result references its source evidence — datasets,
   documents, publications all link back to `source_artifacts` and the
   `provenance_events` chain.
3. Official and derived data are clearly distinguished — `data_class`
   (synthetic/official/mixed/unknown), `derivation_level`,
   `metadata_origin`, `review_status` are carried end-to-end into API
   payloads and UI badges.
4. Uncertain transformations require review — review tasks gate
   georeferencing, machine-extracted metadata, unreviewed rasters, and
   anything ambiguous.
5. Historical versions are preserved — planning versions, artifact
   revisions, and changesets accumulate; nothing is rewritten.
6. Identical bytes are deduplicated — one sha256, one artifact.
7. Crawlers respect public-access boundaries — robots.txt, rate limits,
   no auth/CAPTCHA bypass.
8. Source failures never delete historical evidence.
9. A disappearing upstream URL does not erase previously observed material.
10. OpenQuyHoach never claims legal authority over planning information —
    it is an interoperability and transparency layer.

## Chain of custody

```
official URL ──discover──▶ candidate resource (url, filename, metadata)
        │
        ▼ fetch (SSRF-guarded, robots-aware, conditional)
requested_url + final_url + status + headers + mime + size + sha256
        │
        ▼ stage (immutable)
source_artifacts  ──dedupe──▶  existing artifact reused if sha256 matches
        │                            changed bytes → NEW artifact revision
        ▼ dispatch
documents / datasets / rasters  +  provenance_events
        │
        ▼ resolve + gate
planning_versions (metadata_origin, field_origins, review tasks)
        │
        ▼ publish (conservative)
publications + manifest (source list, checksums, disclaimer)
```

Every `source_artifact` records: source, resource, requested URL, final
URL, fetch timestamp, HTTP status, response headers, MIME, byte size,
SHA-256, storage key — plus a `downloaded`/`unchanged` provenance event.

## Metadata provenance levels

`metadata_origin` on `documents` and `planning_versions`:

| Level | Meaning |
|---|---|
| `official_explicit` | stated by the authority (descriptor/planning block, portal metadata) |
| `derived_deterministic` | rule-based, reproducible (filename parsing, registry joins) |
| `derived_machine` | regex/ML extraction — always review-gated |
| `human_reviewed` | confirmed by a reviewer |
| `unknown` | no reliable origin |

**The weakest origin wins.** A document's `metadata_origin` is the weakest
origin used anywhere on the record — including machine candidates stored in
`meta.candidates` even when not promoted to fields. Machine-extracted
values can never silently upgrade a record to `official_explicit`.

PDF extraction stores per-candidate evidence: `page`, `snippet`, `pattern`,
plus `field_origins` per field, `has_embedded_text`, `needs_ocr`, page
stats. Anything `derived_machine` or `needs_ocr` opens a `review_task`.

## Data classes (real vs demo)

- `demo/*` source keys are reserved for synthetic fixtures — deterministic
  CI/test data with no real-world meaning.
- Records are classified `synthetic` / `official` / `mixed` / `unknown`
  from the source keys behind their artifacts (datasets + documents).
  A record backed by both demo and real sources reports `mixed` — never
  silently "real".
- The UI shows REAL DATA / DEMO / MIXED badges; the provenance drawer
  flags `demo/*` source keys.

## Review gates

`review_tasks` target: `artifact`, `dataset`, `document`, `source`,
`layer`, `feature`. Publication refuses unreviewed derived content unless
`allow_unreviewed` is passed explicitly. Machine-extracted document fields
and OCR-needed scans always open tasks. Resolutions are audited via the
resolve endpoint (`X-Admin-Key`, reviewer + resolution recorded).

## Legal / rights posture

- `rights.redistribution_status` on every source: `allowed` / `restricted`
  / `unknown` / `prohibited`. Unknown stays conservative — metadata +
  provenance stored, republication off.
- `rights_statement`, `license`, `terms_url` are recorded per source and
  surface in manifests.
- Attribution: authority + source links are preserved through API payloads
  and the UI.
- OpenQuyHoach publishes *evidence and derivations*, never a claim that a
  plan is legally valid — every manifest embeds the legal disclaimer.

## Upstream change evidence

`source_change_events` preserve what changed upstream and when:
`added`, `disappeared`, `reappeared`, `checksum_changed`,
`url_changed`, `metadata_changed` — each linked to the resource, the run,
and (for content changes) the from/to artifact revisions. Spatial diffs
between published versions live in `change_sets`/`change_set_entries`
(m² deltas, matched keys, affected classes/bbox).
