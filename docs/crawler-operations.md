# Crawler Operations

How OpenQuyHoach keeps real sources fresh: the crawl-state model, health
semantics, scheduling, and day-2 operations.

## Runtime model (per source)

Descriptor YAML is immutable config. Everything that changes at runtime
lives in Postgres:

| Table | What it answers |
|---|---|
| `source_resources` | Which resources does this source currently expose? `status` ∈ `active`/`disappeared`; `first_seen_at`, `last_seen_at`, `last_changed_at`, last `etag`/`last_modified`/`content_sha256`/`artifact_id` |
| `source_observations` | Append-only log: per run, per resource — `seen_new`, `seen_unchanged`, `seen_changed`, `not_modified`, `disappeared`, `error`, `blocked` |
| `source_crawl_state` | One row per source: `last_check_at`, `last_success_at`, `last_change_at`, `next_check_at`, `consecutive_failures`, `health`, `last_error`, `resources_seen`, `locked_until`/`lock_token` |
| `source_change_events` | First-class upstream changes: `added`, `disappeared`, `reappeared`, `checksum_changed`, `url_changed`, `metadata_changed` (with from/to artifact links) |
| `ingestion_runs` | Per-run stats (discovered/downloaded/skipped/errors/bytes), status `succeeded`/`partial`/`failed` |

Invariants: artifacts are never mutated or deleted; a disappearing upstream
URL marks the resource `disappeared` but preserves all evidence; identical
bytes are deduplicated by sha256; changed bytes produce a *new* artifact
revision linked by the change event.

## Health semantics

`source_crawl_state.health` — set at the end of every run:

| State | Meaning |
|---|---|
| `healthy` | last run succeeded, no changes |
| `unchanged` | succeeded, nothing new (equivalent clean state) |
| `changed` | succeeded AND detected upstream changes |
| `degraded` | partial errors, or 1–2 consecutive fatal failures |
| `failing` | ≥3 consecutive fatal failures |
| `blocked` | robots/policy denied the fetch |
| `needs_review` | pending review tasks attached to the source |
| `disabled` | `enabled: false` in the descriptor |
| `unknown` | never checked |

**"no changes" is not "failed"** — an unchanged run still updates
`last_check_at`/`last_success_at` and resets `consecutive_failures`.

## Freshness semantics

`freshness` derives from `next_check_at` vs now:

- `never_checked` — no successful check yet (treated as due)
- `never_succeeded` — checked but never succeeded (due)
- `fresh` — `next_check_at` in the future
- `overdue` — `next_check_at` passed without a check (due)

Exposed via `/v1/sources`, `/v1/sources/{key}`, `/v1/coverage`,
`/v1/coverage/detail`, and the web sources tab.

## Scheduling

`refresh.interval_seconds` (+`jitter_seconds`) sets the base period;
failures back off by `failure_backoff_multiplier` (default ×2, capped).
`next_check_at` is recomputed at the end of each run.

`openquyhoach_ingest.scheduler`:

- `due_sources()` — enabled sources whose `next_check_at` is due (or null)
  and which hold no live lock, ordered by priority.
- `scheduler_tick()` — claims due sources with an enqueue-lock
  (`lock_token: enqueue:<uuid>`, short TTL), enforces per-host concurrency
  (`rate_limit.concurrent_requests`, default 2), then enqueues
  `sync_source` jobs on the configured queue backend.
- `claim_source()` inside `sync_source` takes over the lock for the actual
  run — no duplicate concurrent runs per source.

Run it: `openquyhoach scheduler tick` (one pass) or
`openquyhoach scheduler loop --interval 60` (daemon). With
`OQH_QUEUE_BACKEND=inline` jobs run in-process; with `redis` they go to
the worker fleet.

## Fetch behaviour

- Conditional GET via stored `etag`/`last_modified` → `If-None-Match` /
  `If-Modified-Since`; `304` short-circuits as `not_modified`.
- SHA-256 over every download; `expected_sha256` verification when known.
- Byte caps: `Content-Length` pre-check + streaming cap (default 512 MB;
  `fetch.max_bytes` per descriptor).
- Retry with backoff on 429/5xx (tenacity).
- SSRF guard validates the URL *and* re-validates the final redirected URL
  (redirect to private/reserved address space is refused).
- `robots.txt` fetched per origin (1h cache): 2xx parsed per RFC 9309
  (matching user-agent group wins over `*`; `Crawl-delay` honoured);
  404/other-4xx → allow; 401/403/5xx/transport failure → deny-all.
- Per-domain rate limiting and per-source `user_agent` override via
  `crawl_policy`.

## CLI

```bash
openquyhoach sources list                # registry + health summary
openquyhoach sources discover <key>      # dry-run discovery
openquyhoach sources sync <key>          # one observation cycle
openquyhoach sources sync-all            # all enabled sources
openquyhoach sources status [<key>]      # health/freshness detail
openquyhoach sources failures            # sources with errors/failures
openquyhoach sources validate            # descriptor schema check
openquyhoach coverage                    # per-unit coverage + freshness
openquyhoach changes recent [--source K] # upstream change events
openquyhoach scheduler tick|loop         # scheduling driver
openquyhoach ocr [--limit N]             # OCR batch for scanned PDFs
```

OCR requires `pdftoppm` (poppler) + `tesseract` with the `vie`
traineddata on PATH. Each document renders ≤ `--max-pages` pages at
`--dpi` (default 200) and OCRs them with `--lang` (default `vie+eng`).
Output is stored on `document.meta['ocr']` with a text sha256, evidence-
bearing candidates, and stays `derived_machine` + review-gated — OCR is
an assisted step, never authoritative. Rough cost: ~30–90 s per scanned
PDF depending on page count; run in batches during quiet hours.

## API / MCP

- `GET /v1/sources[?health=&enabled=&jurisdiction=]` — registry + crawl state
- `GET /v1/sources/{key}` — detail + recent observations + resources
- `GET /v1/changes[?source=&change_type=]` — upstream change events
- `GET /v1/coverage` / `GET /v1/coverage/detail` — coverage + freshness +
  per-source health + pending review counts
- MCP read-only tools: `source_status`, `recent_changes`,
  `planning_versions` (plus `coverage`, `provenance_of`, `point_query`,
  `search_planning`)

## Observability

Structured logs (structlog): `crawl.run` per cycle with
discovered/downloaded/skipped_dup/errors/changed/disappeared/bytes/status;
`crawl.fatal` on site-level failures; `scheduler.enqueued` per enqueue.
`ingestion_runs.meta` persists the same stats + health + duration.

Never logged: secrets, admin tokens, credentials.

## Disaster recovery

- **Postgres + object store are the system of record** — back them up
  together. Artifacts are content-addressed; PMTiles/manifests are
  re-derivable from artifacts + code.
- **Source loss is not data loss** — disappeared upstream resources keep
  their artifacts, documents, datasets, and provenance.
- **Replay** — re-running `sources sync` is idempotent (dedupe by sha256);
  `sources discover` never mutates.
- **Partial failure containment** — per-resource errors mark the run
  `partial`; the source goes `degraded` and backs off without losing state.
