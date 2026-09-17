"""End-to-end ingest pipeline against real PostGIS + local object store.

Uses the synthetic DemoDistrict fixtures — no network access required.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest.fixture()
def descriptor_env(db, local_store, monkeypatch):
    """Point the sources root at the repo's demo descriptors."""
    monkeypatch.setenv("OQH_SOURCES_DIR", "sources")
    return db


def _ingest(key: str):
    from openquyhoach_core.db import session_scope
    from openquyhoach_core.models import IngestionRun
    from openquyhoach_ingest.pipeline import ingest_source

    run_id = ingest_source(key)
    with session_scope() as s:
        run = s.get(IngestionRun, run_id)
        assert run is not None
        assert run.status == "succeeded", run.error_summary
    return run_id


class TestDescriptorSync:
    def test_sync_registers_sources(self, descriptor_env):
        from openquyhoach_ingest.sources import sync_sources

        out = sync_sources()
        assert out["created"] + out["updated"] >= 3, out

        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import Source

        with session_scope() as s:
            keys = {r.source_key for r in s.scalars(select(Source))}
        assert "demo/demo-district-v1" in keys


class TestVectorIngest:
    def test_ingest_v1(self, descriptor_env):
        _ingest("demo/demo-district-v1")

        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import (
            Dataset,
            Feature,
            Layer,
            PlanningRecord,
            PlanningVersion,
            ProvenanceEvent,
            SourceArtifact,
        )

        with session_scope() as s:
            rec = s.scalars(select(PlanningRecord)).one()
            assert "DemoDistrict" in rec.title

            versions = s.scalars(select(PlanningVersion)).all()
            assert len(versions) == 1
            assert versions[0].version_label == "v1"
            assert versions[0].approval_decision_number == "001/QD-UBND-MX"

            datasets = s.scalars(select(Dataset)).all()
            assert datasets
            assert all(d.derivation_level == "official_vector" for d in datasets)

            layers = s.scalars(select(Layer)).all()
            names = {ly.canonical_name for ly in layers}
            assert {"land_use", "transport", "boundary"} <= names

            feats = s.scalars(select(Feature)).all()
            assert len(feats) >= 7  # land-use + transport + boundary
            keys = {f.stable_external_id for f in feats}
            # v1 has ODT/CAY/CN; TT only appears in v2 (the added feature)
            assert {"ODT", "CAY", "CN"} <= keys
            assert "TT" not in keys
            assert s.scalars(select(ProvenanceEvent)).first() is not None
            arts = s.scalars(select(SourceArtifact)).all()
            assert arts and all(len(a.content_sha256) == 64 for a in arts)

    def test_ingest_idempotent_artifact(self, descriptor_env):
        _ingest("demo/demo-district-v1")
        _ingest("demo/demo-district-v1")  # same bytes → same artifact
        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import SourceArtifact

        with session_scope() as s:
            hashes = [a.content_sha256 for a in s.scalars(select(SourceArtifact))]
        assert len(hashes) == len(set(hashes)), "no duplicate artifacts"


class TestDocumentIngest:
    def test_pdf_metadata_extracted(self, descriptor_env):
        _ingest("demo/demo-district-docs")

        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import Document

        with session_scope() as s:
            docs = s.scalars(select(Document)).all()
        assert len(docs) >= 2
        numbers = {d.document_number for d in docs}
        assert "001/QD-UBND-MX" in numbers
        assert all(d.page_count and d.page_count >= 1 for d in docs)


class TestRasterIngest:
    def test_cog_registered_unreviewed(self, descriptor_env):
        _ingest("demo/demo-district-docs")
        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import Dataset, ReviewTask

        with session_scope() as s:
            rasters = [d for d in s.scalars(select(Dataset)) if d.dataset_type == "raster"]
            tasks = s.scalars(select(ReviewTask)).all()
        assert rasters, "COG must register as a raster dataset"
        # unreferenced rasters must generate a human review gate
        assert tasks or any(
            r.review_status in ("needs_review", "pending", "unreviewed") for r in rasters
        )
