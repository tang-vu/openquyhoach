"""Seed the deterministic DemoDistrict demo dataset.

Run after `openquyhoach db init`:

    .venv/bin/python -m scripts.seed_demo

Steps: sync demo sources -> ingest v1 + v2 + docs -> register the admin
unit -> link versions (v2 supersedes v1) -> approve vector datasets ->
georeference the scan (GCPs + approval) -> publish both versions ->
compute the v1->v2 changeset -> coverage summary.
"""

from __future__ import annotations

from pathlib import Path

from openquyhoach_core.db import session_scope
from openquyhoach_core.enums import (
    ProvenanceOp,
    ReviewStatus,
)
from openquyhoach_core.models import (
    AdministrativeUnit,
    Dataset,
    Layer,
    PlanningRecord,
    PlanningVersion,
    SourceArtifact,
)
from openquyhoach_core.provenance import record_event
from openquyhoach_core.text import vn_normalize
from openquyhoach_geo.geom import to_postgis
from openquyhoach_ingest.pipeline import ingest_source
from openquyhoach_ingest.sources import sync_sources
from openquyhoach_services.compare import compute_changeset
from openquyhoach_services.coverage import recompute_coverage
from openquyhoach_services.georef_service import (
    create_job,
    review_job,
    update_gcps,
)
from openquyhoach_services.publish import publish_version
from shapely.geometry import MultiPolygon, box

ROOT = Path(__file__).resolve().parents[1]

LON0, LAT0, DEG = 105.88, 20.93, 0.0375
W, H = 400, 400


def _px_to_lonlat(px: float, py: float) -> tuple[float, float]:
    return LON0 + px / W * DEG, LAT0 + DEG - py / H * DEG


def seed() -> None:
    print(sync_sources())

    run_v1 = ingest_source("demo/demo-district-v1")
    run_v2 = ingest_source("demo/demo-district-v2")
    run_docs = ingest_source("demo/demo-district-docs")
    print(f"ingest runs: v1={run_v1} v2={run_v2} docs={run_docs}")

    with session_scope() as s:
        # --- admin unit -------------------------------------------------
        unit = (
            s.query(AdministrativeUnit)
            .filter_by(normalized_name=vn_normalize("DemoDistrict"))
            .one_or_none()
        )
        if unit is None:
            unit = AdministrativeUnit(
                name="DemoDistrict (SYNTHETIC)",
                normalized_name=vn_normalize("DemoDistrict (SYNTHETIC)"),
                level="district",
                official_code="SYNTH-DEMO-01",
                geometry=to_postgis(MultiPolygon([box(LON0, LAT0, LON0 + DEG, LAT0 + DEG)])),
                meta={"synthetic": True},
            )
            s.add(unit)
            s.flush()

        record = (
            s.query(PlanningRecord)
            .filter_by(normalized_title=vn_normalize("Quy hoạch phân khu DemoDistrict (SYNTHETIC)"))
            .one_or_none()
        )
        assert record is not None, "planning record was not created by ingest"
        record.admin_unit_id = unit.id
        record.jurisdiction = "DemoDistrict"

        versions = (
            s.query(PlanningVersion)
            .filter_by(planning_record_id=record.id)
            .order_by(PlanningVersion.effective_from.nulls_last())
            .all()
        )
        v1 = next(v for v in versions if v.version_label == "v1")
        v2 = next(v for v in versions if v.version_label == "v2")
        v2.supersedes_version_id = v1.id
        from datetime import date

        v1.effective_to = date(2025, 1, 14)
        v2.version_kind = "amendment"
        s.flush()
        print(f"record={record.id} v1={v1.id} v2={v2.id} unit={unit.id}")

        # --- review gate: approve vector datasets (simulated reviewer) --
        datasets = s.query(Dataset).filter(Dataset.planning_version_id.in_([v1.id, v2.id])).all()
        for d in datasets:
            if d.dataset_type == "vector" and d.review_status != ReviewStatus.APPROVED.value:
                d.review_status = ReviewStatus.APPROVED.value
                record_event(
                    s,
                    entity_type="dataset",
                    entity_id=d.id,
                    operation=ProvenanceOp.HUMAN_REVIEWED,
                    parameters={"approved": True, "demo": True},
                    actor="seed-reviewer",
                    actor_type="human",
                )

        # --- georeference the scan --------------------------------------
        scan = s.query(SourceArtifact).filter_by(filename="ban_do_quy_hoach_scan.png").one_or_none()
        assert scan is not None
        scan_ds = s.query(Dataset).filter_by(source_artifact_id=scan.id).one_or_none()
        s.flush()
        scan_id, scan_ds_id = scan.id, (scan_ds.id if scan_ds else None)
        v1_id, v2_id = v1.id, v2.id

    job_id = create_job(
        scan_id,
        transform_type="affine",
        dataset_id=scan_ds_id,
        suggestion_source="manual",
    )
    gcps = []
    for i, (px, py) in enumerate(
        [
            (40, 40),
            (200, 40),
            (360, 40),
            (40, 200),
            (200, 200),
            (360, 200),
            (40, 360),
            (200, 360),
            (360, 360),
        ]
    ):
        lon, lat = _px_to_lonlat(px, py)
        gcps.append(
            {
                "id": f"g{i + 1}",
                "pixel_x": px,
                "pixel_y": py,
                "map_x": lon,
                "map_y": lat,
                "enabled": True,
                "origin": "manual",
            }
        )
    # one deliberate outlier to demonstrate RANSAC rejection
    gcps.append(
        {
            "id": "g-bad",
            "pixel_x": 120,
            "pixel_y": 120,
            "map_x": _px_to_lonlat(300, 300)[0],
            "map_y": _px_to_lonlat(300, 300)[1],
            "enabled": True,
            "origin": "manual",
        }
    )
    res = update_gcps(job_id, gcps, actor="seed-reviewer")
    print(f"georef rmse={res['rmse']} rejected={res['rejected']}")
    review_job(
        job_id,
        approve=True,
        reviewer="seed-reviewer",
        notes="synthetic demo scan; GCPs on grid intersections",
    )

    # --- publish both versions -----------------------------------------
    pub1 = publish_version(v1_id, actor="seed")
    pub2 = publish_version(v2_id, actor="seed")
    print(f"publications: v1={pub1} v2={pub2}")

    # --- changeset between land_use v1 -> v2 ---------------------------
    with session_scope() as s:
        layers = {
            (str(ly.dataset.planning_version_id), ly.canonical_name): ly.id
            for ly in s.query(Layer).join(Dataset).all()
        }
    lu_from = layers[(str(v1_id), "land_use")]
    lu_to = layers[(str(v2_id), "land_use")]
    cs = compute_changeset(lu_from, lu_to)
    print(f"changeset={cs}")

    print(f"coverage rows written: {recompute_coverage()}")
    print("seed complete")


if __name__ == "__main__":
    seed()
