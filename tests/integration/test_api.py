"""FastAPI surface tests — real app, test DB, local store."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest.fixture()
def api(db, local_store, monkeypatch):
    monkeypatch.setenv("OQH_SOURCES_DIR", "sources")
    from openquyhoach_api.app import create_app

    return TestClient(create_app())


@pytest.fixture()
def seeded_api(api, monkeypatch):
    """Ingest v1+v2+docs, publish v1, return ids."""
    from openquyhoach_core.db import session_scope
    from openquyhoach_core.models import (
        Dataset,
        PlanningVersion,
    )
    from openquyhoach_ingest.pipeline import ingest_source
    from openquyhoach_ingest.sources import sync_sources
    from openquyhoach_services.publish import publish_version

    sync_sources()
    ingest_source("demo/demo-district-v1")
    ingest_source("demo/demo-district-v2")
    ingest_source("demo/demo-district-docs")

    with session_scope() as s:
        versions = {v.version_label: v.id for v in s.scalars(select(PlanningVersion))}
        raster = next(
            d
            for d in s.scalars(select(Dataset))
            if d.dataset_type == "raster" and d.derivation_level == "official_raster"
        )
        raster_id = raster.id
    pub_id = publish_version(versions["v1"], max_zoom=8)
    return {"api": api, "versions": versions, "pub_id": pub_id, "raster_id": raster_id}


class TestHealth:
    def test_healthz(self, api):
        r = api.get("/healthz")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestSearch:
    def test_search_finds_record(self, seeded_api):
        r = seeded_api["api"].get("/v1/search", params={"q": "DemoDistrict"})
        assert r.status_code == 200
        results = r.json()["results"]
        assert any(x["kind"] == "planning_record" for x in results)


class TestTiles:
    def test_live_mvt_tile(self, seeded_api):
        api = seeded_api["api"]
        # find a tile that intersects the data — publication tiles are known
        pub = seeded_api["pub_id"]
        r = api.get(f"/v1/publications/{pub}/manifest.json")
        assert r.status_code == 200
        manifest = r.json()
        assert manifest["pmtiles_sha256"]
        assert manifest["schema_version"]
        assert "does not certify legal validity" in manifest["disclaimer"]

        # pull a real tile from the archive
        r = api.get(f"/v1/publications/{pub}/tiles/8/205/116.pbf")
        # tile may or may not exist at that coord; contract is 200-with-pbf or 404
        assert r.status_code in (200, 404)

    def test_raster_tile_requires_publish(self, seeded_api):
        api = seeded_api["api"]
        raster_id = seeded_api["raster_id"]
        # COG is official_raster but `published` flips only when its *version*
        # is published — v1 publication doesn't cover the docs version
        r = api.get(f"/v1/rasters/{raster_id}/tiles/8/205/116.png")
        assert r.status_code == 403

        # publish the docs version (PNG scan is unreviewed → override needed
        # in tests; production would resolve the review task instead)
        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import Dataset
        from openquyhoach_services.publish import publish_version

        with session_scope() as s:
            d = s.get(Dataset, raster_id)
            docs_version = d.planning_version_id
        publish_version(docs_version, allow_unreviewed=True, max_zoom=8)

        # compute a tile that actually covers the COG (~105.9E, 20.95N)
        import mercantile

        t = mercantile.tile(105.9, 20.95, 13)
        r = api.get(f"/v1/rasters/{raster_id}/tiles/{t.z}/{t.x}/{t.y}.png")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "image/png"
        assert r.content[:4] == b"\x89PNG"

        # far-away tile → 404, not 500
        r = api.get(f"/v1/rasters/{raster_id}/tiles/13/0/0.png")
        assert r.status_code == 404

    def test_raster_tile_404_unknown(self, api):
        import uuid

        r = api.get(f"/v1/rasters/{uuid.uuid4()}/tiles/8/0/0.png")
        assert r.status_code == 404


class TestCompareApi:
    def test_compare_endpoint(self, seeded_api):
        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import Dataset, Layer

        api = seeded_api["api"]
        with session_scope() as s:
            ds = {d.id: d for d in s.scalars(select(Dataset))}
            lu = [
                (ds[ly.dataset_id].planning_version_id, ly.id)
                for ly in s.scalars(select(Layer))
                if ly.canonical_name == "land_use"
            ]
        v1, v2 = seeded_api["versions"]["v1"], seeded_api["versions"]["v2"]
        l1 = next(lid for vid, lid in lu if vid == v1)
        l2 = next(lid for vid, lid in lu if vid == v2)

        r = api.get("/v1/compare", params={"from_layer": str(l1), "to_layer": str(l2)})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["summary"]["added"] == 1


class TestDocuments:
    def _doc_ids(self):
        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import Document

        with session_scope() as s:
            return {d.id: d for d in s.scalars(select(Document))}

    def test_list_documents(self, seeded_api):
        r = seeded_api["api"].get("/v1/documents")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] >= 1
        item = body["items"][0]
        assert {"id", "document_type", "document_number", "artifact_id"} <= set(item)

    def test_list_documents_version_filter(self, seeded_api):
        api = seeded_api["api"]
        docs = self._doc_ids()
        vid = next(iter(docs.values())).planning_version_id
        r = api.get("/v1/documents", params={"version_id": str(vid)})
        assert r.status_code == 200
        items = r.json()["items"]
        assert items and all(d["planning_version_id"] == str(vid) for d in items)
        r = api.get("/v1/documents", params={"version_id": str(seeded_api["versions"]["v1"])})
        assert r.json()["total"] == 0

    def test_document_detail_has_artifact(self, seeded_api):
        api = seeded_api["api"]
        doc_id = next(iter(self._doc_ids()))
        r = api.get(f"/v1/documents/{doc_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == str(doc_id)
        assert body["artifact"]["sha256"]

    def test_document_download_streams_bytes(self, seeded_api):
        """LocalStore presigns as file:// → endpoint streams raw bytes."""
        import hashlib

        api = seeded_api["api"]
        docs = self._doc_ids()
        doc = next(d for d in docs.values() if d.artifact_id)
        from openquyhoach_core.db import session_scope
        from openquyhoach_core.models import SourceArtifact

        with session_scope() as s:
            a = s.get(SourceArtifact, doc.artifact_id)
            sha, fname = a.content_sha256, a.filename
        r = api.get(f"/v1/documents/{doc.id}/download")
        assert r.status_code == 200, r.text
        assert hashlib.sha256(r.content).hexdigest() == sha
        assert fname in r.headers["content-disposition"]

    def test_document_404s(self, api):
        import uuid

        missing = uuid.uuid4()
        assert api.get(f"/v1/documents/{missing}").status_code == 404
        assert api.get(f"/v1/documents/{missing}/download").status_code == 404


class TestAdminGuard:
    def test_mutating_requires_key(self, seeded_api):
        api = seeded_api["api"]
        r = api.post("/v1/publish", json={"planning_version_id": str(seeded_api["versions"]["v2"])})
        assert r.status_code == 403
        r = api.post(
            "/v1/publish",
            json={"planning_version_id": str(seeded_api["versions"]["v2"]), "max_zoom": 6},
            headers={"X-Admin-Key": "dev-admin-token"},
        )
        assert r.status_code in (200, 409), r.text
