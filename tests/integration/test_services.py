"""Service-layer integration: publish → PMTiles → compare → provenance."""

from __future__ import annotations

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest.fixture()
def seeded(db, local_store, monkeypatch):
    """Ingest v1+v2 into the test DB; return version/layer ids."""
    monkeypatch.setenv("OQH_SOURCES_DIR", "sources")
    from openquyhoach_core.db import session_scope
    from openquyhoach_core.models import (
        Dataset,
        Layer,
        PlanningVersion,
    )
    from openquyhoach_ingest.pipeline import ingest_source
    from openquyhoach_ingest.sources import sync_sources

    sync_sources()
    ingest_source("demo/demo-district-v1")
    ingest_source("demo/demo-district-v2")

    with session_scope() as s:
        versions = {v.version_label: v.id for v in s.scalars(select(PlanningVersion))}
        # version_id -> label for reverse lookup
        label_of = {vid: label for label, vid in versions.items()}
        ds_map = {d.id: d for d in s.scalars(select(Dataset))}
        land_use_layers = {}
        for ly in s.scalars(select(Layer)):
            if ly.canonical_name == "land_use":
                label = label_of[ds_map[ly.dataset_id].planning_version_id]
                land_use_layers[label] = ly.id
    return {"versions": versions, "land_use_layers": land_use_layers}


class TestPublish:
    def test_publish_official_allowed(self, seeded):
        from openquyhoach_services.publish import publish_version

        pub_id = publish_version(seeded["versions"]["v1"], max_zoom=8)
        assert pub_id

        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import Publication

        with session_scope() as s:
            pub = s.get(Publication, pub_id)
            assert pub.checksum_sha256
            assert pub.feature_count > 0  # stores tile count
            assert pub.status == "published"

    def test_pmtiles_roundtrip_via_storage(self, seeded, local_store):
        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import Publication
        from openquyhoach_core.storage import published_store
        from openquyhoach_geo.pmtiles import PMTilesReader
        from openquyhoach_services.publish import publish_version

        pub_id = publish_version(seeded["versions"]["v1"], max_zoom=8)
        with session_scope() as s:
            pub = s.get(Publication, pub_id)
            key = pub.artifact_key
            sha = pub.checksum_sha256

        data = published_store().get(key)
        import hashlib

        assert hashlib.sha256(data).hexdigest() == sha
        reader = PMTilesReader(data)
        meta = reader.metadata()
        assert meta.get("vector_layers"), "manifest metadata must name layers"

    def test_unreviewed_blocked(self, seeded, db):
        # mark a dataset as machine-unreviewed derived → publish must refuse
        from openquyhoach_core.db import session_scope
        from openquyhoach_core.errors import UnreviewedDataError
        from openquyhoach_core.models import Dataset
        from openquyhoach_services.publish import publish_version

        with session_scope() as s:
            d = s.scalars(select(Dataset)).first()
            d.derivation_level = "derived_machine_unreviewed"
            d.review_status = "unreviewed"
        with pytest.raises(UnreviewedDataError):
            publish_version(seeded["versions"]["v1"])
        # but explicit override works
        pub_id = publish_version(seeded["versions"]["v1"], allow_unreviewed=True)
        assert pub_id


class TestCompare:
    def test_changeset_semantics(self, seeded):
        from openquyhoach_services.compare import compute_changeset

        cs_id = compute_changeset(
            seeded["land_use_layers"]["v1"],
            seeded["land_use_layers"]["v2"],
        )
        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import ChangeSet, ChangeSetEntry

        with session_scope() as s:
            cs = s.get(ChangeSet, cs_id)
            summary = cs.summary
            assert summary["added"] == 1  # TT
            assert summary["geometry_changed"] == 3  # ODT/CAY/CN
            assert summary["removed"] == 0
            entries = s.scalars(
                select(ChangeSetEntry).where(ChangeSetEntry.change_set_id == cs_id)
            ).all()
        # entries are per-change-type: a feature that both moved and had
        # attribute edits contributes two entries
        by_type = {}
        for e in entries:
            by_type[e.change_type] = by_type.get(e.change_type, 0) + 1
        assert by_type.get("added") == 1
        assert by_type.get("geometry_changed") == 3
        assert by_type.get("properties_changed") == 3

    def test_changeset_cached(self, seeded):
        from openquyhoach_services.compare import compute_changeset

        a = compute_changeset(seeded["land_use_layers"]["v1"], seeded["land_use_layers"]["v2"])
        b = compute_changeset(seeded["land_use_layers"]["v1"], seeded["land_use_layers"]["v2"])
        assert a == b


class TestProvenance:
    def test_feature_provenance_summary(self, seeded):
        """Every feature must trace: dataset → version → artifact → source."""
        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import Feature
        from openquyhoach_services.provenance_service import (
            provenance_summary_for_feature,
        )

        with session_scope() as s:
            fid = s.scalars(select(Feature.id)).first()
        prov = provenance_summary_for_feature(fid)
        assert prov["dataset"]["id"]
        assert prov["artifact"]["sha256"] and len(prov["artifact"]["sha256"]) == 64
        assert prov["source"]["key"] == "demo/demo-district-v1"
        assert prov["planning_version"]["label"] == "v1"
        assert prov["derivation_level"] == "official_vector"

    def test_dataset_event_graph(self, seeded):
        """The event graph links dataset → artifact."""
        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import Dataset
        from openquyhoach_services.provenance_service import provenance_graph

        with session_scope() as s:
            did = s.scalars(select(Dataset.id)).first()
        graph = provenance_graph("dataset", did)
        kinds = {n["entity_type"] for n in graph["nodes"]}
        assert "dataset" in kinds
        assert "artifact" in kinds
        assert graph["edges"], "provenance must have edges"
