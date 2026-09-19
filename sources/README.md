# Source registry

Every YAML file here is an immutable *source descriptor* — validated by
`_schema/source-descriptor.schema.json` (`make sources-validate`).

Layout:

```
sources/
  _schema/                      descriptor JSON Schema
  demo/                         SYNTHETIC fixtures — CI/test only, never real data
  vietnam/
    national/                   national-level official sources
    provinces/<province>/       provincial official sources
```

Rules:

* **`key` is identity, path is organisation.** Administrative
  reorganisation changes `jurisdiction`/`admin_codes`, never the key.
  Keys may be deeper than two segments
  (`vietnam/provinces/da-nang/qh-chung`); the filename must equal the
  last key segment.
* **No mutable crawl state in YAML.** Last-checked timestamps, ETags,
  failure counts live in the database (`source_crawl_state`,
  `source_resources`, `source_observations`), never in descriptors.
  Descriptors may record `refresh:` *policy* and `provenance:` *who
  verified this source, when, and on what evidence*.
* **`enabled: false`** keeps a source registered but uncrawled — use it
  for sources pending legal/robots review, with `rights.access_notes`
  explaining why.
* **Never fabricate.** `base_url`, `homepage`, `authority`,
  `admin_codes`, `rights` must be verified before committing; record
  the verification in `provenance.evidence`.

See `docs/source-onboarding.md` for the full authoring guide.
