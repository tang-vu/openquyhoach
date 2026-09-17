"""Job queue abstraction.

Pipeline business logic lives in `openquyhoach_ingest.pipeline` and is
queue-agnostic. Two backends:

* ``InlineQueue`` — runs the job synchronously (default for CLI/dev/tests).
* ``RedisQueue`` — a BLPOP-based durable-ish queue, one list per queue name.
  Workers call ``worker_loop``; jobs are JSON payloads ``{name, kwargs}``.

Deliberately small: at national scale this can be swapped for a heavier
scheduler without touching pipeline code.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from .logging import get_logger
from .settings import get_settings

log = get_logger(__name__)

JobHandler = Callable[..., Any]

_registry: dict[str, JobHandler] = {}


def register_job(name: str) -> Callable[[JobHandler], JobHandler]:
    def deco(fn: JobHandler) -> JobHandler:
        _registry[name] = fn
        return fn

    return deco


def get_handler(name: str) -> JobHandler:
    if name not in _registry:
        raise KeyError(f"no job handler registered for {name!r}")
    return _registry[name]


@runtime_checkable
class JobQueue(Protocol):
    def enqueue(self, name: str, **kwargs: Any) -> str: ...


class InlineQueue:
    def enqueue(self, name: str, **kwargs: Any) -> str:
        job_id = uuid.uuid4().hex
        log.info("job.inline.start", job=name, job_id=job_id)
        get_handler(name)(**kwargs)
        return job_id


class RedisQueue:
    def __init__(self, redis_url: str | None = None, queue_name: str = "oqh:jobs"):
        import redis

        self._r = redis.Redis.from_url(redis_url or get_settings().redis_url)
        self._q = queue_name

    def enqueue(self, name: str, **kwargs: Any) -> str:
        job_id = uuid.uuid4().hex
        payload = {"id": job_id, "name": name, "kwargs": kwargs}
        self._r.rpush(self._q, json.dumps(payload))
        log.info("job.redis.enqueued", job=name, job_id=job_id)
        return job_id

    def worker_loop(self, *, once: bool = False, timeout: int = 5) -> None:
        log.info("worker.loop.start", queue=self._q)
        while True:
            item = self._r.blpop(self._q, timeout=timeout)
            if item is None:
                if once:
                    return
                continue
            _, raw = item
            try:
                payload = json.loads(raw)
                handler = get_handler(payload["name"])
                handler(**payload.get("kwargs", {}))
                log.info("job.done", job=payload["name"], job_id=payload.get("id"))
            except Exception as exc:
                log.exception("job.failed", raw=raw[:200], error=str(exc))
                self._r.rpush(f"{self._q}:failed", raw)
            if once:
                return


def get_queue() -> JobQueue:
    s = get_settings()
    if s.queue_backend == "redis":
        return RedisQueue(s.redis_url)
    return InlineQueue()


def worker_main(queue_name: str = "oqh:jobs", once: bool = False) -> None:
    # importing registers handlers
    import openquyhoach_ingest.jobs  # noqa: F401

    RedisQueue(queue_name=queue_name).worker_loop(once=once)
