"""Source scheduler — decides *what to check next* and enqueues sync jobs.

Design:

* `scheduler_tick()` is itself a queue job (`scheduler_tick`) plus a CLI
  command — any cron/systemd timer/worker beat can invoke it. The repo does
  not depend on GitHub Actions for crawling.
* A source is due when its `source_crawl_state.next_check_at` is NULL
  (never crawled) or <= now, the source is enabled, and no lock is held.
* Enqueueing stamps a short ``enqueue:<job_id>`` reservation lock — a
  second tick won't double-enqueue; a dead worker's reservation expires
  and the source becomes eligible again.
* Per-host concurrency: reservations+live locks are counted per URL host
  and capped by the descriptor's ``rate_limit.concurrent_requests``
  (default 2). Global enqueue volume per tick is capped to keep one tick
  cheap.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from openquyhoach_core.db import session_scope
from openquyhoach_core.logging import get_logger
from openquyhoach_core.models import Source, SourceCrawlState
from openquyhoach_core.queue import get_queue
from sqlalchemy import or_

from .crawl import get_or_create_state
from .sources import load_config

log = get_logger(__name__)

ENQUEUE_TTL_S = 900  # reservation lives 15 min; dead workers free the source
DEFAULT_HOST_CONCURRENCY = 2
DEFAULT_TICK_LIMIT = 20


def _host(url: str | None) -> str:
    return urlparse(url or "").hostname or "local"


def due_sources(now: datetime | None = None, limit: int = 500) -> list[tuple]:
    """Enabled sources whose next_check is due (or never scheduled) and
    which hold no live lock. Ordered by priority then earliest due."""
    now = now or datetime.now(UTC)
    with session_scope() as s:
        rows = (
            s.query(Source)
            .outerjoin(SourceCrawlState, SourceCrawlState.source_id == Source.id)
            .filter(Source.enabled.is_(True))
            .filter(
                or_(
                    SourceCrawlState.next_check_at.is_(None),
                    SourceCrawlState.next_check_at <= now,
                )
            )
            .filter(
                or_(
                    SourceCrawlState.locked_until.is_(None),
                    SourceCrawlState.locked_until <= now,
                )
            )
            .order_by(Source.priority.asc(), Source.id.asc())
            .limit(limit)
            .all()
        )
        # detach: ids+keys only needed downstream
        return [(r.id, r.source_key, r.base_url) for r in rows]


def _host_load(s) -> dict[str, int]:
    """Current live locks (reservations + running) grouped by URL host."""
    now = datetime.now(UTC)
    rows = (
        s.query(Source.base_url, SourceCrawlState.lock_token)
        .join(SourceCrawlState, SourceCrawlState.source_id == Source.id)
        .filter(SourceCrawlState.locked_until > now)
        .all()
    )
    load: dict[str, int] = {}
    for base_url, _token in rows:
        h = _host(base_url)
        load[h] = load.get(h, 0) + 1
    return load


def _host_cap(source_key: str) -> int:
    try:
        cfg = load_config(source_key)
        return int((cfg.rate_limit or {}).get("concurrent_requests") or DEFAULT_HOST_CONCURRENCY)
    except Exception:
        return DEFAULT_HOST_CONCURRENCY


def scheduler_tick(*, tick_limit: int = DEFAULT_TICK_LIMIT, now: datetime | None = None) -> dict:
    """Enqueue sync jobs for due sources. Returns a tick report.

    Reservations are committed *before* jobs are enqueued — with the
    inline queue the job runs synchronously inside enqueue(), so the lock
    must already be durable for its claim to see it.
    """
    now = now or datetime.now(UTC)
    report = {"enqueued": [], "skipped_host_limit": [], "due": 0}
    due = due_sources(now)
    report["due"] = len(due)
    chosen: list[str] = []
    with session_scope() as s:
        host_load = _host_load(s)
        for source_id, source_key, base_url in due:
            if len(chosen) >= tick_limit:
                break
            host = _host(base_url)
            cap = _host_cap(source_key)
            if host_load.get(host, 0) >= cap:
                report["skipped_host_limit"].append(source_key)
                continue
            state = get_or_create_state(s, source_id)
            state.lock_token = f"enqueue:{uuid.uuid4().hex}"
            state.locked_until = now + timedelta(seconds=ENQUEUE_TTL_S)
            chosen.append(source_key)
            host_load[host] = host_load.get(host, 0) + 1
    queue = get_queue()
    for source_key in chosen:
        job_id = queue.enqueue("sync_source", source_key=source_key)
        log.info("scheduler.enqueued", source=source_key, job=job_id)
        report["enqueued"].append(source_key)
    return report


def scheduler_loop(interval_s: int = 60, *, once: bool = False) -> None:
    """Standalone tick loop for a scheduler deployment.

    `once` runs a single tick — the deterministic-test and manual path."""
    log.info("scheduler.loop.start", interval_s=interval_s)
    while True:
        report = scheduler_tick()
        log.info("scheduler.tick", **{k: len(v) if isinstance(v, list) else v for k, v in report.items()})
        if once:
            return
        time.sleep(interval_s)
