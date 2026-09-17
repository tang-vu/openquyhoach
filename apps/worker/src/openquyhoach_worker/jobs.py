"""Service-layer queue jobs (registered here to keep ingest free of the
services dependency)."""

from __future__ import annotations

import uuid

from openquyhoach_core.queue import register_job


@register_job("publish_version")
def job_publish_version(
    planning_version_id: str, max_zoom: int = 14, allow_unreviewed: bool = False
) -> str:
    from openquyhoach_services.publish import publish_version

    return str(
        publish_version(
            uuid.UUID(planning_version_id),
            max_zoom=max_zoom,
            allow_unreviewed=allow_unreviewed,
            actor="worker",
        )
    )


@register_job("recompute_coverage")
def job_recompute_coverage() -> int:
    from openquyhoach_services.coverage import recompute_coverage

    return recompute_coverage()


@register_job("compute_changeset")
def job_compute_changeset(from_layer: str, to_layer: str) -> str:
    from openquyhoach_services.compare import compute_changeset

    return str(compute_changeset(uuid.UUID(from_layer), uuid.UUID(to_layer)))
