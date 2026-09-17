# Design Guidelines

## Product design

1. **Provenance first.** Every displayed fact must be one click away from
   its evidence: source file, sha256, retrieval time, decision number,
   review status. If provenance is missing, say so — never fill gaps.
2. **Official ≠ derived ≠ unreviewed.** Distinct visual treatment always
   (green / amber / red badges in the UI; `derivation_level` +
   `review_status` in the API).
3. **Honest absence.** "No published geometry at this point" is a coverage
   statement, not a legal one — the UI says exactly that.
4. **Versions are history.** Users can select and compare any published
   version; nothing silently replaces an older plan on the map.
5. **Geometric ≠ legal.** Diff outputs show areas and changes; copy always
   adds that verification belongs with the authority.

## UI conventions (apps/web)

- Dark GIS console: `--bg #0f1419`, panels `--panel #171e26`,
  accent `--accent #3fa7ff`; official green `#35c48d`, derived amber
  `#e8b13f`, unreviewed red `#e05a5a`.
- Three-pane shell: records/versions + search (left), MapLibre map
  (center), point-query provenance drawer (right). Collapses to stacked
  rows under 900px.
- Map has no external basemap dependency — published MVT layers only
  (works offline, no third-party tile terms).
- Admin tab stores the dev token in `localStorage` — development only,
  documented as such.

## API design

- `/v1/*` REST; pagination via `PageDep` (`page`, `size` →
  `{total, items}`); admin mutations behind `X-Admin-Key`.
- Errors: `{"error": code, "message", "detail"}`; 404s carry a specific
  `detail` string; tiles return 404 for out-of-bounds (map-client normal).
- MVT features carry `layer` (canonical name) + `id` as properties; numeric
  UUIDs are never used as MVT feature ids.
- PMTiles are immutable per publication (`artifact_key` includes the
  manifest checksum prefix).
