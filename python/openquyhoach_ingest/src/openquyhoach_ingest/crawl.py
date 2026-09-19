"""Crawl/sync runner — turns connector output into persistent crawl state.

One `sync_source` call performs a full observation cycle for a source:

  claim run -> robots gate -> discover -> upsert SourceResource rows
  -> conditional fetch per resource -> SourceObservation per attempt
  -> stage artifacts (immutable, deduplicated) -> detect upstream changes
  (added / disappeared / reappeared / checksum / url / metadata)
  -> update SourceCrawlState (health, counters, next_check_at)

Historical evidence is never deleted: a disappearing URL only marks the
resource `disappeared`; artifacts and observations remain.
"""

from __future__ import annotations

import hashlib
import random
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from openquyhoach_core.db import session_scope
from openquyhoach_core.enums import (
    ChangeType,
    IngestionStatus,
    ObservationOutcome,
    ResourceStatus,
    SourceHealth,
)
from openquyhoach_core.errors import ConflictError, SourceDisabledError
from openquyhoach_core.logging import get_logger
from openquyhoach_core.models import (
    IngestionRun,
    ReviewTask,
    Source,
    SourceArtifact,
    SourceChangeEvent,
    SourceCrawlState,
    SourceObservation,
    SourceResource,
)
from openquyhoach_core.robots import robots_allowed
from openquyhoach_core.settings import get_settings

from .connectors.base import DiscoveredItem, get_connector
from .pipeline import _git_commit, stage_artifact
from .sources import ensure_source_row, load_config

log = get_logger(__name__)

MAX_FAILURE_BACKOFF_S = 6 * 3600  # cap exponential failure backoff at 6h


class FatalBlocked(Exception):
    """Robots/policy refusal — the run is 'blocked', not 'failed'."""


# ---------------------------------------------------------------------------
# helpers


def canonicalize_url(url: str, rules: dict | None = None) -> str:
    """Apply the descriptor's canonical_url policy. Defaults are conservative:
    lowercase scheme/host, strip fragment, sort query params."""
    rules = rules or {}
    parts = urlparse(url)
    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()
    if rules.get("strip_default_port", True) and (
        (scheme == "http" and netloc.endswith(":80"))
        or (scheme == "https" and netloc.endswith(":443"))
    ):
        netloc = netloc.rsplit(":", 1)[0]
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    if rules.get("strip_query"):
        params = {}
    for p in rules.get("strip_params", []) or []:
        params.pop(p, None)
    keep = rules.get("keep_params")
    if keep:
        params = {k: v for k, v in params.items() if k in keep}
    query = urlencode(sorted(params.items()) if rules.get("sort_params", True) else params.items())
    fragment = "" if rules.get("strip_fragment", True) else parts.fragment
    return urlunparse((scheme, netloc, parts.path, parts.params, query, fragment))


def resource_key_for(item: DiscoveredItem, canonical_url: str) -> str:
    """Stable identity for a discovered resource. Prefer the connector-
    supplied identity (e.g. ArcGIS service+layer id, CKAN resource id);
    fall back to the canonical URL digest."""
    if item.identity:
        return f"id:{item.identity}"[:128]
    digest = hashlib.sha256(canonical_url.encode()).hexdigest()[:48]
    return f"u:{digest}"


def get_or_create_state(s, source_id: uuid.UUID) -> SourceCrawlState:
    state = s.query(SourceCrawlState).filter_by(source_id=source_id).one_or_none()
    if state is None:
        state = SourceCrawlState(source_id=source_id)
        s.add(state)
        s.flush()
    return state


def claim_source(s, source: Source, state: SourceCrawlState, ttl_s: int = 3600) -> str:
    """Soft lock so two runs never process one source concurrently.
    Returns the lock token; raises ConflictError when already claimed.

    A token starting with ``enqueue:`` is a scheduler reservation, not a
    running crawl — the enqueued run takes it over when it starts.
    """
    now = datetime.now(UTC)
    if (
        state.locked_until
        and state.locked_until > now
        and not (state.lock_token or "").startswith("enqueue:")
    ):
        raise ConflictError(
            f"source {source.source_key} already running",
            detail={"locked_until": state.locked_until.isoformat()},
        )
    token = uuid.uuid4().hex
    state.lock_token = token
    state.locked_until = now + timedelta(seconds=ttl_s)
    s.flush()
    return token


def next_check_at(cfg, failed: bool, consecutive_failures: int) -> datetime:
    refresh = cfg.refresh or {}
    base = int(refresh.get("interval_seconds") or 86400)
    jitter = float(refresh.get("jitter_seconds") or 300)
    if failed:
        base = min(
            base
            * (float(refresh.get("failure_backoff_multiplier") or 2.0) ** min(consecutive_failures, 6)),
            MAX_FAILURE_BACKOFF_S,
        )
    return datetime.now(UTC) + timedelta(seconds=base + random.uniform(0, jitter))


def _health_after(
    source: Source,
    run_status: str,
    blocked: bool,
    had_errors: bool,
    had_changes: bool,
    consecutive_failures: int,
    needs_review: bool,
) -> str:
    if not source.enabled:
        return SourceHealth.DISABLED.value
    if blocked:
        return SourceHealth.BLOCKED.value
    if run_status == IngestionStatus.FAILED.value:
        return (
            SourceHealth.FAILING.value
            if consecutive_failures >= 3
            else SourceHealth.DEGRADED.value
        )
    if had_errors:
        return SourceHealth.DEGRADED.value
    if needs_review:
        return SourceHealth.NEEDS_REVIEW.value
    if had_changes:
        return SourceHealth.CHANGED.value
    return SourceHealth.UNCHANGED.value


def _needs_review(s, source_id: uuid.UUID) -> bool:
    return (
        s.query(ReviewTask)
        .filter(
            ReviewTask.target_type == "source",
            ReviewTask.target_id == source_id,
            ReviewTask.status == "pending",
        )
        .count()
        > 0
    )


# ---------------------------------------------------------------------------
# main entry


def sync_source(
    source_key: str,
    *,
    trigger: str = "manual",
    limit: int | None = None,
    download: bool = True,
    workdir: Path | None = None,
    dry_run: bool = False,
) -> uuid.UUID:
    """Run one observation cycle for `source_key`. Returns the run id."""
    started = datetime.now(UTC)
    settings = get_settings()
    cfg = load_config(source_key)
    connector = get_connector(cfg.source_type)
    if not cfg.enabled:
        raise SourceDisabledError(f"source '{source_key}' disabled")

    workdir_ctx = (
        tempfile.TemporaryDirectory(prefix="oqh-fetch-") if workdir is None else None
    )
    try:
        wd = Path(workdir_ctx.name) if workdir_ctx else workdir
        with session_scope() as s:
            source = ensure_source_row(s, source_key)
            if source is None:
                raise ConflictError(f"no descriptor/source for key '{source_key}'")
            if not source.enabled:
                raise SourceDisabledError(f"source '{source_key}' disabled")
            state = get_or_create_state(s, source.id)
            claim_source(s, source, state)
            run = IngestionRun(
                source_id=source.id,
                status=IngestionStatus.RUNNING.value,
                trigger=trigger,
                software_commit=_git_commit(),
                meta={"dry_run": dry_run},
            )
            s.add(run)
            s.flush()
            state.last_run_id = run.id
            stats = {
                "discovered": 0,
                "downloaded": 0,
                "skipped_dup": 0,
                "errors": 0,
                "changed": 0,
                "disappeared": 0,
                "bytes": 0,
            }
            fatal: str | None = None
            seen_keys: set[str] = set()
            try:
                _run_cycle(
                    s,
                    cfg,
                    source,
                    state,
                    run,
                    connector,
                    stats,
                    seen_keys,
                    download=download and not dry_run,
                    limit=limit,
                    workdir=wd,
                    settings=settings,
                )
            except FatalBlocked as exc:
                fatal = f"blocked:{exc}"
            except Exception as exc:  # fatal — discovery/site failure
                fatal = f"{type(exc).__name__}: {exc}"
                log.warning("crawl.fatal", source=source_key, error=fatal)
            _mark_disappeared(
                s, source, run, seen_keys, stats, full=limit is None and fatal is None
            )
            _finish(s, source, state, run, stats, fatal, started, cfg)
            log.info(
                "crawl.run",
                source=source_key,
                run=str(run.id),
                status=run.status,
                **stats,
            )
            return run.id
    finally:
        if workdir_ctx:
            workdir_ctx.cleanup()


# ---------------------------------------------------------------------------
# cycle internals


def _run_cycle(
    s,
    cfg,
    source: Source,
    state: SourceCrawlState,
    run: IngestionRun,
    connector,
    stats: dict,
    seen_keys: set[str],
    *,
    download: bool,
    limit: int | None,
    workdir: Path,
    settings,
) -> None:
    policy = cfg.crawl_policy or {}
    respect = bool(policy.get("respect_robots", True))
    ua = policy.get("user_agent")
    discovery_urls = (cfg.discovery or {}).get("urls") or []
    gate_url = cfg.base_url or (discovery_urls[0] if discovery_urls else None)
    if respect and gate_url and not robots_allowed(gate_url, settings, ua):
        s.add(
            SourceObservation(
                source_id=source.id,
                run_id=run.id,
                outcome=ObservationOutcome.BLOCKED.value,
                detail={"reason": "robots_disallow", "url": gate_url},
            )
        )
        stats["errors"] += 1
        raise FatalBlocked("robots_disallow")

    items: list[DiscoveredItem] = []
    for item in connector.discover(cfg):
        items.append(item)
        if limit and len(items) >= limit:
            break
    stats["discovered"] = len(items)

    rules = cfg.canonical_url or {}
    resources: dict[str, SourceResource] = {}
    for item in items:
        canon = canonicalize_url(item.url, rules)
        rkey = resource_key_for(item, canon)
        seen_keys.add(rkey)
        res = (
            s.query(SourceResource)
            .filter_by(source_id=source.id, resource_key=rkey)
            .one_or_none()
        )
        now = datetime.now(UTC)
        if res is None:
            res = SourceResource(
                source_id=source.id,
                resource_key=rkey,
                url=item.url,
                canonical_url=canon,
                title=item.metadata.get("title"),
                status=ResourceStatus.ACTIVE.value,
                first_seen_at=now,
                last_seen_at=now,
                discovered_metadata=item.metadata or {},
                meta={"last_discovery_metadata": item.metadata or {}},
            )
            s.add(res)
            s.flush()
            _change(s, source, run, res, ChangeType.ADDED, {"url": item.url})
            stats["changed"] += 1
        else:
            if res.status == ResourceStatus.DISAPPEARED.value:
                res.status = ResourceStatus.ACTIVE.value
                _change(s, source, run, res, ChangeType.REAPPEARED, {"url": item.url})
                stats["changed"] += 1
                res.last_changed_at = now
            if res.canonical_url and res.canonical_url != canon:
                _change(
                    s,
                    source,
                    run,
                    res,
                    ChangeType.URL_CHANGED,
                    {"from": res.canonical_url, "to": canon},
                )
                stats["changed"] += 1
                res.last_changed_at = now
            res.canonical_url = canon
            res.url = item.url
            res.last_seen_at = now
            last_disc = (res.meta or {}).get("last_discovery_metadata") or {}
            if (item.metadata or {}) != last_disc:
                _change(
                    s,
                    source,
                    run,
                    res,
                    ChangeType.METADATA_CHANGED,
                    {"from": last_disc, "to": item.metadata or {}},
                )
                stats["changed"] += 1
                res.meta = {**(res.meta or {}), "last_discovery_metadata": item.metadata or {}}
        resources[rkey] = res

    if not download:
        return

    for item in items:
        canon = canonicalize_url(item.url, rules)
        rkey = resource_key_for(item, canon)
        res = resources[rkey]
        _fetch_one(s, cfg, source, run, res, item, connector, stats, workdir, respect, settings)


def _fetch_one(
    s,
    cfg,
    source: Source,
    run: IngestionRun,
    res: SourceResource,
    item: DiscoveredItem,
    connector,
    stats: dict,
    workdir: Path,
    respect_robots: bool,
    settings,
) -> None:
    obs = SourceObservation(
        source_id=source.id, run_id=run.id, resource_id=res.id, detail={"url": item.url}
    )
    if respect_robots and not robots_allowed(
        item.url, settings, (cfg.crawl_policy or {}).get("user_agent")
    ):
        obs.outcome = ObservationOutcome.BLOCKED.value
        obs.detail = {"url": item.url, "reason": "robots_disallow"}
        s.add(obs)
        stats["errors"] += 1
        return
    # hand stored validators to the connector for conditional requests
    item.etag = item.etag or res.etag
    item.last_modified = item.last_modified or res.last_modified
    try:
        result = connector.fetch(cfg, item, workdir)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code if exc.response is not None else None
        obs.outcome = ObservationOutcome.ERROR.value
        obs.http_status = code
        obs.detail = {"url": item.url, "error": str(exc)[:500]}
        s.add(obs)
        res.http_status = code
        res.consecutive_failures += 1
        res.last_error = str(exc)[:500]
        stats["errors"] += 1
        return
    except Exception as exc:
        obs.outcome = ObservationOutcome.ERROR.value
        obs.detail = {"url": item.url, "error": f"{type(exc).__name__}: {exc}"[:500]}
        s.add(obs)
        res.consecutive_failures += 1
        res.last_error = f"{type(exc).__name__}: {exc}"[:500]
        stats["errors"] += 1
        return

    now = datetime.now(UTC)
    if result.not_modified:
        obs.outcome = ObservationOutcome.NOT_MODIFIED.value
        obs.http_status = result.http_status or 304
        s.add(obs)
        res.consecutive_failures = 0
        res.last_error = None
        res.http_status = 304
        res.last_seen_at = now
        return

    obs.http_status = result.http_status
    obs.content_sha256 = result.sha256
    obs.etag = result.etag
    obs.last_modified = result.last_modified
    obs.detail = {
        "url": item.url,
        "retrieved_url": result.retrieved_url,
        "size_bytes": result.size,
        "response_headers": result.response_headers or {},
    }

    prior_sha = res.content_sha256
    prior_artifact = res.artifact_id
    first_fetch = prior_sha is None
    # keep the discovered filename + metadata on the artifact record
    result.filename = result.filename or item.suggested_filename
    result.metadata = item.metadata or {}
    try:
        report = stage_artifact(s, result, source, cfg, run)
    except Exception as exc:
        obs.outcome = ObservationOutcome.ERROR.value
        obs.detail["error"] = f"stage: {type(exc).__name__}: {exc}"[:450]
        s.add(obs)
        res.consecutive_failures += 1
        res.last_error = f"stage: {type(exc).__name__}: {exc}"[:500]
        stats["errors"] += 1
        return

    obs.artifact_id = uuid.UUID(report["artifact_id"]) if report.get("artifact_id") else None
    artifact = s.get(SourceArtifact, obs.artifact_id) if obs.artifact_id else None
    if artifact is not None:
        fetch_meta = {
            "requested_url": item.url,
            "retrieved_url": result.retrieved_url,
            "http_status": result.http_status,
            "response_headers": result.response_headers,
            "fetched_at": now.isoformat(),
        }
        artifact.meta = {**(artifact.meta or {}), "fetch": fetch_meta}

    res.etag = result.etag or res.etag
    res.last_modified = result.last_modified or res.last_modified
    res.content_sha256 = result.sha256
    res.file_size = result.size
    res.artifact_id = obs.artifact_id
    res.http_status = result.http_status
    res.consecutive_failures = 0
    res.last_error = None
    res.last_seen_at = now
    stats["downloaded"] += 1
    stats["bytes"] += result.size
    if report.get("skipped"):
        stats["skipped_dup"] += 1

    if first_fetch:
        obs.outcome = ObservationOutcome.SEEN_NEW.value
    elif result.sha256 != prior_sha:
        obs.outcome = ObservationOutcome.SEEN_CHANGED.value
        res.last_changed_at = now
        _change(
            s,
            source,
            run,
            res,
            ChangeType.CHECKSUM_CHANGED,
            {"from_sha256": prior_sha, "to_sha256": result.sha256},
            from_artifact=prior_artifact,
            to_artifact=obs.artifact_id,
        )
        stats["changed"] += 1
    else:
        obs.outcome = ObservationOutcome.SEEN_UNCHANGED.value
    s.add(obs)


def _mark_disappeared(s, source, run, seen_keys, stats, *, full: bool) -> None:
    """Resources not rediscovered on a *complete* run are marked disappeared.
    Their artifacts stay — evidence is never deleted."""
    if not full:
        return
    missing = (
        s.query(SourceResource)
        .filter(
            SourceResource.source_id == source.id,
            SourceResource.status == ResourceStatus.ACTIVE.value,
            ~SourceResource.resource_key.in_(seen_keys or {"-"}),
        )
        .all()
    )
    for res in missing:
        res.status = ResourceStatus.DISAPPEARED.value
        s.add(
            SourceObservation(
                source_id=source.id,
                run_id=run.id,
                resource_id=res.id,
                outcome=ObservationOutcome.DISAPPEARED.value,
                detail={"url": res.url},
            )
        )
        _change(s, source, run, res, ChangeType.DISAPPEARED, {"url": res.url})
        stats["disappeared"] += 1


def _change(
    s,
    source,
    run,
    res: SourceResource,
    ctype: ChangeType,
    detail: dict,
    *,
    from_artifact: uuid.UUID | None = None,
    to_artifact: uuid.UUID | None = None,
) -> None:
    s.add(
        SourceChangeEvent(
            source_id=source.id,
            resource_id=res.id,
            run_id=run.id,
            change_type=ctype.value,
            detail=detail,
            from_artifact_id=from_artifact,
            to_artifact_id=to_artifact,
        )
    )


def _finish(s, source, state, run, stats, fatal, started, cfg) -> None:
    now = datetime.now(UTC)
    blocked = fatal is not None and fatal.startswith("blocked:")
    run.completed_at = now
    run.discovered_count = stats["discovered"]
    run.downloaded_count = stats["downloaded"]
    run.rejected_count = stats["errors"]
    if fatal and not blocked:
        run.status = IngestionStatus.FAILED.value
        run.error_summary = fatal[:4000]
    elif stats["errors"] and stats["downloaded"] == 0 and stats["discovered"] == 0:
        run.status = IngestionStatus.FAILED.value
        run.error_summary = (fatal or "all fetches failed")[:4000]
    elif stats["errors"]:
        run.status = IngestionStatus.PARTIAL.value
    else:
        run.status = IngestionStatus.SUCCEEDED.value

    state.last_check_at = now
    state.last_run_id = run.id
    state.resources_seen = (
        s.query(SourceResource)
        .filter_by(source_id=source.id, status=ResourceStatus.ACTIVE.value)
        .count()
    )
    if run.status == IngestionStatus.FAILED.value:
        state.consecutive_failures += 1
        state.last_error = run.error_summary
    else:
        state.consecutive_failures = 0
        state.last_success_at = now
        state.last_error = None if run.status == IngestionStatus.SUCCEEDED.value else run.error_summary
    if stats["changed"] or stats["disappeared"]:
        state.last_change_at = now
    state.next_check_at = next_check_at(
        cfg,
        failed=run.status == IngestionStatus.FAILED.value,
        consecutive_failures=state.consecutive_failures,
    )
    state.health = _health_after(
        source,
        run_status=run.status,
        blocked=blocked,
        had_errors=bool(stats["errors"]),
        had_changes=bool(stats["changed"] or stats["disappeared"]),
        consecutive_failures=state.consecutive_failures,
        needs_review=_needs_review(s, source.id),
    )
    run.meta = {
        **(run.meta or {}),
        "stats": stats,
        "bytes_downloaded": stats["bytes"],
        "skipped_duplicates": stats["skipped_dup"],
        "health": state.health,
        "blocked": blocked,
        "duration_s": (now - started).total_seconds(),
    }
    # lock released — the claim lives only for the duration of this call
    state.lock_token = None
    state.locked_until = None
