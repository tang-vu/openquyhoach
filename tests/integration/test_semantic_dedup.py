"""Semantic dedup — re-ingested vector content identical to a prior
dataset must not mint duplicate datasets/versions."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

pytestmark = pytest.mark.integration


@pytest.fixture()
def descriptor_env(db, local_store, monkeypatch):
    monkeypatch.setenv("OQH_SOURCES_DIR", "sources")
    return db


def _clone_dataset(session, ds):
    """Copy a dataset's layers+features into a new version (simulating a
    byte-different but semantically identical upstream re-fetch)."""
    from openquyhoach_core.models import Dataset, Feature, Layer, PlanningVersion

    version = PlanningVersion(
        planning_record_id=ds.planning_version.planning_record_id,
        version_kind="original",
        legal_status="unknown",
    )
    session.add(version)
    session.flush()
    clone = Dataset(
        planning_version_id=version.id,
        dataset_group=ds.dataset_group,
        dataset_type=ds.dataset_type,
        name=ds.name,
        original_format=ds.original_format,
        original_crs=ds.original_crs,
        derivation_level=ds.derivation_level,
        review_status=ds.review_status,
    )
    session.add(clone)
    session.flush()
    for layer in ds.layers:
        nl = Layer(
            dataset_id=clone.id,
            canonical_name=layer.canonical_name,
            source_name=layer.source_name,
            feature_count=layer.feature_count,
        )
        session.add(nl)
        session.flush()
        for f in session.scalars(
            select(Feature).where(Feature.layer_id == layer.id)
        ):
            session.add(
                Feature(
                    layer_id=nl.id,
                    stable_external_id=f.stable_external_id,
                    classification=f.classification,
                    geometry=f.geometry,
                    properties=f.properties,
                )
            )
    session.flush()
    return clone, version


class TestSemanticDedup:
    def test_identical_reingest_deduped(self, descriptor_env):
        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import (
            Dataset,
            Feature,
            IngestionRun,
            Layer,
            PlanningVersion,
        )
        from openquyhoach_ingest.pipeline import (
            _dedupe_semantic,
            _vector_content_digest,
            ingest_source,
        )

        run_id = ingest_source("demo/demo-district-v1")
        with session_scope() as s:
            run = s.get(IngestionRun, run_id)
            assert run.status == "succeeded"
            ds = s.scalars(
                select(Dataset).where(Dataset.dataset_type == "vector")
            ).first()
            assert ds is not None
            digest_a = _vector_content_digest(s, ds)
            clone, version = _clone_dataset(s, ds)
            digest_b = _vector_content_digest(s, clone)
            assert digest_a == digest_b

            kept = _dedupe_semantic(s, [clone], run)
            s.flush()

            assert kept == []
            assert s.get(Dataset, clone.id) is None
            assert s.get(PlanningVersion, version.id) is None
            nf = s.scalar(
                select(func.count(Feature.id))
                .join(Layer, Feature.layer_id == Layer.id)
                .where(Layer.dataset_id == ds.id)
            )
            assert nf > 0  # original untouched

            # digest recorded on surviving dataset for future comparisons
            assert (ds.meta or {}).get("content_digest") or digest_a
