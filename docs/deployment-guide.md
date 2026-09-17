# Deployment Guide

## Local development (verified)

Prereqs: Docker, Python ≥3.12, Node ≥20, pnpm, uv.

```bash
cp .env.example .env
make setup        # uv sync --all-packages && pnpm install
make infra        # docker compose: db (PostGIS), minio (+init buckets), redis
make migrate      # alembic upgrade head
make seed         # demo district: ingest v1+v2+docs, georef, publish, compare
make api          # uvicorn :8000
make web-serve    # static web on :3100   (or `make web` for next dev)
```

Verify: `make doctor`, `make sources-validate`,
`curl localhost:8000/healthz`, open http://localhost:3100.

## Services (docker-compose.yml)

| Service | Image | Port |
|---|---|---|
| `db` | local build: `postgres:17` + `postgis-3` via PGDG | 5432 |
| `minio` | `minio/minio:RELEASE.2025-09-07T16-13-09Z` | 9000/9001 |
| `redis` | `valkey/valkey:9.1.1-alpine` (Redis-compatible) | 6379 |

`minio-init` creates buckets `oqh-artifacts` and `oqh-published`.
Dockerfiles pin tags; no `latest`.

## Configuration (`OQH_*` env)

- `OQH_DATABASE_URL` — `postgresql+psycopg://…`
- `OQH_S3_ENDPOINT/ACCESS_KEY/SECRET_KEY/BUCKET_ARTIFACTS/BUCKET_PUBLISHED/SECURE`
- `OQH_QUEUE_BACKEND` — `inline` (default) or `redis`; `OQH_REDIS_URL`
- `OQH_API_CORS_ORIGINS` — comma list; must include the web origin
- `OQH_ADMIN_TOKEN` — required for all mutating endpoints (`X-Admin-Key`)
- `OQH_API_MAX_BBOX_DEG2` — bbox query guard
- `NEXT_PUBLIC_OQH_API_URL` — web → API base (default `http://localhost:8000`)
- `OQH_AI_ENABLED=false` default — no AI provider needed

## Production notes

- Terminate TLS in front of API; put web `out/` on any static host/CDN.
- Swap MinIO for any S3 backend via `OQH_S3_*`; swap Valkey for Redis.
- Run worker (`make worker` / `openquyhoach-worker`) with
  `OQH_QUEUE_BACKEND=redis` for background ingest/georef jobs.
- Rotate `OQH_ADMIN_TOKEN`; do not expose it client-side (the dev UI stores
  it in localStorage for demo only).
- Back up Postgres + object store together; PMTiles/manifests are
  content-addressed and re-derivable from artifacts + code.
- Manifests are unsigned in V1 (format designed for signing — see roadmap).

## Known environment caveat (WSL)

Under WSL2, files on `/mnt/*` (DrvFs/9P) can stall Node/Python servers
during heavy startup I/O. If `next dev`/`next start` hangs, prefer the
static export (`make web-serve`) or run from a native ext4 path. Postgres,
MinIO, and Valkey run in Docker and are unaffected.
