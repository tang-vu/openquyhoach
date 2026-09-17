# Code Standards

## Python

- 3.12+, Ruff for lint+format (`make lint`, `make format`), mypy clean
  (`make typecheck`).
- SQLAlchemy 2 style; `session_scope()` for units of work; no naked engine
  calls outside `db.py`.
- Pydantic-settings for config; never read `os.environ` directly outside
  `settings.py`.
- Errors: raise `OQHError(code, http_status, detail)` for domain failures;
  FastAPI maps it to `{"error","message","detail"}`. Let unexpected errors
  hit the generic 500 handler — do not blanket try/except.
- NumPy guard: never rely on truthiness of arrays — use `is None` /
  `len(...)`.
- Geo: never hardcode a VN-2000 EPSG zone; use `crs.py` detection
  (base-geodetic CRS 4756). Geometries stored as EPSG:4326; original CRS
  recorded in `original_crs`.
- Security: all outbound HTTP through `check_url_allowed`; archives through
  `safe_extract_zip` limits; admin checks via `secrets.compare_digest`.
- Provenance: any code that creates/modifies geometry or derives data must
  emit a `provenance_events` row with input artifact refs.

## TypeScript / web

- Next.js App Router, client components for interactivity, typed API calls
  only through `lib/api.ts` — no ad-hoc `fetch` in components.
- Show `derivation_level`/`review_status` visually everywhere data appears
  (official ≠ derived ≠ unreviewed).
- Never present derived or approximate geometry as authoritative; keep the
  legal disclaimer visible in compare/provenance contexts.

## Tests

- Unit tests must not need Docker; integration tests use the `integration`
  marker + `openquyhoach_test` DB.
- Fixtures are synthetic; a test must never assert real-world legal meaning.
- Every claimed feature needs a test (publication gates, RANSAC rejection,
  duplicate-tile PMTiles rejection, SSRF blocks, idempotent artifacts).

## Files

- Keep modules focused; split when a file grows past ~200 lines.
- Descriptive names; kebab-case only where the repo already uses it.
- Docs live in `docs/`; update `implementation-status.md` when scope shifts.
