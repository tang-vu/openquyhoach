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

For a production-browser check (Python 3 and Chromium are required):

```
pnpm --filter @openquyhoach/web exec playwright install --with-deps chromium
pnpm --filter @openquyhoach/web test:browser
```

This starts a temporary loopback server for the existing static build.
API responses are synthetic and intercepted before any network request;
all other non-local requests are blocked. No published map layers are
loaded. The server and browser are closed afterward. Screenshots, the
request ledger, and tested Git commit/tree IDs go to `.browser-evidence/`.
The Web workflow runs these checks and retains the browser evidence.
