"""Integration tests for crawl state, change detection, and the scheduler.

A throwaway ``file://`` fixture source is used so no network is needed; the
source's file directory is mutated between syncs to exercise the
added/disappeared/reappeared/unchanged change-detection paths.

Fixture files use a ``.dat`` extension with no recognizable magic bytes, so
``sniff_format`` leaves them unhandled: they are staged as immutable
artifacts and observed, but skip the vector/document ingestors — keeping the
tests focused on the crawl machinery itself.
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration

SOURCE_KEY = "test/change-watch"


@pytest.fixture()
def watched_source(db, local_store, monkeypatch, tmp_path):
    """Descriptor + fixture dir under a temp sources root.

    Returns the files dir; the caller mutates it then resyncs.
    """
    sroot = tmp_path / "sources"
    fdir = tmp_path / "files"
    sroot.mkdir()
    fdir.mkdir()
    (fdir / "a.dat").write_bytes(b"fixture-a-v1\n")
    (fdir / "b.dat").write_bytes(b"fixture-b-v1\n")

    desc = textwrap.dedent(
        f"""\
        key: {SOURCE_KEY}
        name: "Change-watch fixture (TEST ONLY)"
        authority: "Test Authority (SYNTHETIC)"
        jurisdiction: "TestDistrict"
        source_type: file
        base_url: "file://{fdir}"
        discovery:
          path: "{fdir}"
          globs: ["*.dat"]
        refresh:
          interval_seconds: 3600
        planning:
          title: "Change-watch fixture plan (SYNTHETIC)"
          planning_type: quy_hoach_phan_khu
        rights:
          license: "CC0-1.0"
          rights_statement: "Synthetic test fixture."
          redistribution_status: allowed
        enabled: true
        """
    )
    (sroot / f"{SOURCE_KEY.replace('/', '_')}.yaml").write_text(desc)

    from openquyhoach_core.settings import get_settings

    monkeypatch.setenv("OQH_SOURCES_DIR", str(sroot))
    get_settings.cache_clear()
    yield fdir
    get_settings.cache_clear()


def _sync(**kw):
    from openquyhoach_ingest.crawl import sync_source

    return sync_source(SOURCE_KEY, **kw)


def _snapshot():
    from openquyhoach_core.db import session_scope
    from openquyhoach_core.models import (
        Source,
        SourceChangeEvent,
        SourceCrawlState,
        SourceObservation,
        SourceResource,
    )

    with session_scope() as s:
        source = s.scalars(
            select(Source).where(Source.source_key == SOURCE_KEY)
        ).one()
        state = s.scalars(
            select(SourceCrawlState).where(SourceCrawlState.source_id == source.id)
        ).one()
        resources = (
            s.scalars(
                select(SourceResource)
                .where(SourceResource.source_id == source.id)
                .order_by(SourceResource.url)
            )
            .all()
        )
        events = (
            s.scalars(
                select(SourceChangeEvent)
                .where(SourceChangeEvent.source_id == source.id)
                .order_by(SourceChangeEvent.detected_at, SourceChangeEvent.id)
            )
            .all()
        )
        observations = (
            s.scalars(
                select(SourceObservation)
                .where(SourceObservation.source_id == source.id)
                .order_by(SourceObservation.observed_at, SourceObservation.id)
            )
            .all()
        )
        s.expunge_all()
    return source, state, resources, events, observations


class TestCrawlState:
    def test_first_sync_records_resources_and_state(self, watched_source):
        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import IngestionRun

        run_id = _sync()
        _source, state, resources, events, observations = _snapshot()

        with session_scope() as s:
            run = s.get(IngestionRun, run_id)
            assert run.status == "succeeded", run.error_summary

        assert len(resources) == 2
        assert all(r.status == "active" for r in resources)
        assert all(r.first_seen_at is not None for r in resources)
        # artifacts are content-addressed and immutable evidence
        assert all(r.content_sha256 for r in resources)
        assert all(r.artifact_id for r in resources)

        assert {o.outcome for o in observations} == {"seen_new"}
        assert len(observations) == 2
        assert {e.change_type for e in events} == {"added"}
        assert len(events) == 2

        assert state.last_check_at is not None
        assert state.last_success_at is not None
        assert state.last_change_at is not None
        assert state.consecutive_failures == 0
        assert state.health == "changed"
        assert state.next_check_at is not None
        assert state.resources_seen == 2
        # lock released after the run
        assert state.lock_token is None
        assert state.locked_until is None

    def test_second_sync_unchanged(self, watched_source):
        _sync()
        _sync()
        _source, state, resources, events, observations = _snapshot()

        assert len(resources) == 2
        assert len(observations) == 4
        # second run sees identical bytes -> deduped, no new artifacts
        assert sorted(o.outcome for o in observations) == [
            "seen_new",
            "seen_new",
            "seen_unchanged",
            "seen_unchanged",
        ]
        # no new change events on an identical listing
        assert len(events) == 2
        assert state.health == "unchanged"
        assert state.consecutive_failures == 0

        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import SourceArtifact

        with session_scope() as s:
            assert len(s.scalars(select(SourceArtifact)).all()) == 2

    def test_disappeared_and_reappeared(self, watched_source):
        _sync()
        (watched_source / "b.dat").unlink()
        _sync()

        _source, _state, resources, events, observations = _snapshot()
        by_name = {r.url.rsplit("/", 1)[-1]: r for r in resources}
        assert by_name["a.dat"].status == "active"
        assert by_name["b.dat"].status == "disappeared"
        assert any(e.change_type == "disappeared" for e in events)
        assert any(o.outcome == "disappeared" for o in observations)

        # reappearing resource is revived, not duplicated
        (watched_source / "b.dat").write_bytes(b"fixture-b-v1\n")
        _sync()
        _source, _state, resources, events, _obs = _snapshot()
        assert len(resources) == 2
        assert all(r.status == "active" for r in resources)
        assert any(e.change_type == "reappeared" for e in events)

    def test_changed_bytes_new_artifact_revision(self, watched_source):
        _sync()
        (watched_source / "a.dat").write_bytes(b"fixture-a-v2-changed\n")
        _sync()

        _source, state, resources, events, observations = _snapshot()
        a = next(r for r in resources if r.url.endswith("a.dat"))
        b = next(r for r in resources if r.url.endswith("b.dat"))

        # changed file: new sha on the resource + checksum_changed event
        # linking the old and new artifact revisions
        ev = [e for e in events if e.change_type == "checksum_changed"]
        assert len(ev) == 1
        assert ev[0].resource_id == a.id
        assert ev[0].from_artifact_id is not None
        assert ev[0].to_artifact_id is not None
        assert ev[0].from_artifact_id != ev[0].to_artifact_id
        assert a.last_changed_at is not None
        assert any(o.outcome == "seen_changed" for o in observations)
        # unchanged sibling stays put
        assert not any(e.resource_id == b.id for e in ev)
        assert state.health == "changed"

        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import SourceArtifact

        with session_scope() as s:
            arts = s.scalars(select(SourceArtifact)).all()
        # 2 originals + 1 new revision = 3 immutable artifacts
        assert len(arts) == 3
        assert len({a.content_sha256 for a in arts}) == 3


class TestScheduler:
    def test_due_sources_includes_never_checked(self, watched_source):
        from openquyhoach_ingest.scheduler import due_sources
        from openquyhoach_ingest.sources import sync_sources

        sync_sources()
        keys = [k for _id, k, _url in due_sources()]
        assert SOURCE_KEY in keys

    def test_due_respects_next_check_and_lock(self, watched_source):
        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import Source, SourceCrawlState
        from openquyhoach_ingest.scheduler import due_sources
        from openquyhoach_ingest.sources import sync_sources

        sync_sources()

        def due_keys():
            return [k for _id, k, _u in due_sources()]

        # not yet due when next_check_at is in the future
        with session_scope() as s:
            src = s.scalars(
                select(Source).where(Source.source_key == SOURCE_KEY)
            ).one()
            s.add(
                SourceCrawlState(
                    source_id=src.id,
                    next_check_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
        assert SOURCE_KEY not in due_keys()

        # a live lock also excludes the source even when due
        with session_scope() as s:
            src = s.scalars(
                select(Source).where(Source.source_key == SOURCE_KEY)
            ).one()
            st = s.scalars(
                select(SourceCrawlState).where(
                    SourceCrawlState.source_id == src.id
                )
            ).one()
            st.next_check_at = datetime.now(UTC) - timedelta(minutes=1)
            st.locked_until = datetime.now(UTC) + timedelta(hours=1)
            st.lock_token = "test-lock"
        assert SOURCE_KEY not in due_keys()

        # expired lock -> due again
        with session_scope() as s:
            src = s.scalars(
                select(Source).where(Source.source_key == SOURCE_KEY)
            ).one()
            st = s.scalars(
                select(SourceCrawlState).where(
                    SourceCrawlState.source_id == src.id
                )
            ).one()
            st.locked_until = datetime.now(UTC) - timedelta(minutes=1)
        assert SOURCE_KEY in due_keys()

    def test_failure_backoff_and_health(self, watched_source, monkeypatch):
        """A fatal discovery error -> failed run, degraded health, backoff."""
        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import IngestionRun
        from openquyhoach_ingest.connectors.file import FileConnector

        def boom(_self, _cfg):
            raise RuntimeError("simulated upstream outage")

        monkeypatch.setattr(FileConnector, "discover", boom)

        run_id = _sync()
        _source, state, _res, _ev, _obs = _snapshot()
        with session_scope() as s:
            run = s.get(IngestionRun, run_id)
            assert run.status == "failed", run.error_summary
            assert "simulated upstream outage" in (run.error_summary or "")

        assert state.consecutive_failures >= 1
        assert state.health == "degraded"
        assert state.last_error
        # backoff pushes next_check beyond the normal 3600s interval
        assert state.next_check_at is not None
        assert state.next_check_at > datetime.now(UTC) + timedelta(
            seconds=3600
        )

        # a second consecutive failure raises the counter
        _sync()
        _source, state, _r, _e, _o = _snapshot()
        assert state.consecutive_failures == 2
