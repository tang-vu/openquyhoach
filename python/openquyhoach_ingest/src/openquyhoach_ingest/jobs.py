"""Queue job registrations for ingestion — imported by the worker entrypoint.

Handlers are thin wrappers so queue payloads stay JSON-serialisable.
Service-layer jobs (publish/compare/coverage) live in the worker package
because ingest must not depend on openquyhoach-services.
"""

from __future__ import annotations

from openquyhoach_core.logging import get_logger
from openquyhoach_core.queue import register_job

log = get_logger(__name__)


@register_job("ingest_source")
def job_ingest_source(source_key: str, dry_run: bool = False) -> str:
    from .pipeline import ingest_source

    return str(ingest_source(source_key, dry_run=dry_run))


@register_job("ingest_url")
def job_ingest_url(url: str, source_key: str | None = None, dry_run: bool = False) -> str:
    from .pipeline import ingest_url

    return str(ingest_url(url, source_key=source_key, dry_run=dry_run))


@register_job("sync_sources")
def job_sync_sources() -> dict:
    from .sources import sync_sources

    return sync_sources()
