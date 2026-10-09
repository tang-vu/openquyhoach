# Web checks

From the repository root, install with the declared pnpm version:

```
pnpm install --frozen-lockfile --ignore-scripts
pnpm --filter @openquyhoach/web test
pnpm --filter @openquyhoach/web typecheck
pnpm --filter @openquyhoach/web build
```

The component tests use synthetic JSON, deferred promises, a MapLibre event
stub, and a replaced fetch implementation. They do not load datasets or
contact map providers. They cover point-query failure/empty/hit states,
malformed responses, repeated clicks, response ordering, and map cleanup
under React StrictMode.

Navigation tests also cover record/version response ownership, empty and failed
records, version details and manifests, repeated A→B→A selections, late
publication catalogs, map framing, and old-record comparison callbacks. They
preserve deliberately selected same-record comparisons and independent point
queries. A post-load source-busy regression ensures tile loading cannot postpone
raster or publication cleanup. All fixtures and MapLibre sources are synthetic.

For a production-browser check (Python 3 and Chromium are required):

```
pnpm --filter @openquyhoach/web exec playwright install --with-deps chromium
pnpm --filter @openquyhoach/web test:browser
```

This starts a temporary loopback server for the existing static build.
API responses are synthetic and intercepted before any network request;
all other non-local requests are blocked. Navigation scenarios load generated
synthetic vector and raster tiles; no real planning datasets or providers are
used. The server and browser are closed afterward. Screenshots, the
request ledger, and tested Git commit/tree IDs go to `.browser-evidence/`.
The Web workflow runs these checks and retains the browser evidence.

The browser suite preserves the seven point-query checks and covers nine
navigation scenarios, including response reversal, A→B→A, empty-record layer
clearing, provenance/manifest ownership, framing and comparison preservation.
It checks the real DOM, center-point coordinates and fresh synthetic tile
requests without instrumenting product code.

Metadata snapshot checks cover value preservation, every returned metadata
entry, explicit unavailable manifests, required response structure/identity,
unsafe publication IDs, and preparation/download ownership under StrictMode.
A direct component replacement test inspects the committed DOM in a layout
effect, before passive cleanup, to ensure an old capture is never offered.

Nine additional browser scenarios exercise actual local JSON downloads and
their contents, incomplete/no-manifest choices, malformed or foreign metadata,
retries, duplicate activation, cancellation, record/version navigation and tab
unmounts. Complete and incomplete choices are exercised at both wide and
390px widths, including ordinary sidebar scrolling, visible/hit-testable
controls, Tab/Enter activation, screenshots and retained download bytes.
The snapshot fixtures use only synthetic metadata and the existing
network interceptor. An existing Chromium binary can be selected with
`OQH_BROWSER_EXECUTABLE=/absolute/path/to/chromium`; otherwise Playwright uses
its normal installed Chromium.
