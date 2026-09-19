"""`openquyhoach` CLI.

openquyhoach doctor
openquyhoach sources list|validate|inspect <key>
openquyhoach ingest file|url|source|inspect|retry
openquyhoach validate <path>
openquyhoach publish <planning-version-id>
openquyhoach compare <layer-a> <layer-b>
openquyhoach db check|init|seed
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import typer
from openquyhoach_core.logging import configure_logging
from openquyhoach_core.settings import get_settings
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="openquyhoach", no_args_is_help=True, add_completion=False)
sources_app = typer.Typer(name="sources", no_args_is_help=True)
ingest_app = typer.Typer(name="ingest", no_args_is_help=True)
db_app = typer.Typer(name="db", no_args_is_help=True)
scheduler_app = typer.Typer(name="scheduler", no_args_is_help=True)
changes_app = typer.Typer(name="changes", no_args_is_help=True)
app.add_typer(sources_app)
app.add_typer(ingest_app)
app.add_typer(db_app)
app.add_typer(scheduler_app)
app.add_typer(changes_app)
console = Console()
err = Console(stderr=True)


@app.callback()
def _main(verbose: bool = typer.Option(False, "--verbose", "-v")):
    configure_logging("DEBUG" if verbose else get_settings().log_level, get_settings().log_format)


# ---------------------------------------------------------------- doctor


@app.command()
def doctor():
    """Diagnose the environment: DB/PostGIS, object store, queue, GDAL/PROJ."""
    checks: list[tuple[str, bool, str]] = []

    # python + geo stack
    import sys as _sys

    checks.append(("python", True, _sys.version.split()[0]))
    for mod, label in (("rasterio", "gdal"), ("pyproj", "proj"), ("shapely", "geos")):
        try:
            m = __import__(mod)
            checks.append(
                (
                    label,
                    True,
                    getattr(m, "__version__", "?") if mod != "rasterio" else m.__gdal_version__,
                )
            )
        except ImportError:
            checks.append((label, False, "not installed"))

    # DB + PostGIS
    try:
        from openquyhoach_core.db import get_engine
        from sqlalchemy import text

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            pv = conn.execute(text("SELECT PostGIS_Version()")).scalar()
        checks.append(("postgres", True, "connect ok"))
        checks.append(("postgis", True, str(pv)))
    except Exception as exc:
        checks.append(("postgres", False, str(exc)[:120]))
        checks.append(("postgis", False, "unreachable"))

    # object store
    try:
        from openquyhoach_core.storage import artifact_store

        store = artifact_store()
        if hasattr(store, "ensure_bucket"):
            store.ensure_bucket()
        checks.append(("s3/minio", True, get_settings().s3_endpoint))
    except Exception as exc:
        checks.append(("s3/minio", False, str(exc)[:120]))

    # queue
    try:
        if get_settings().queue_backend == "redis":
            import redis

            redis.Redis.from_url(get_settings().redis_url).ping()
            checks.append(("redis", True, get_settings().redis_url))
        else:
            checks.append(("queue", True, "inline"))
    except Exception as exc:
        checks.append(("redis", False, str(exc)[:120]))

    # sources dir
    from openquyhoach_ingest.sources import iter_descriptors, validate_all

    descs = iter_descriptors()
    issues = validate_all()
    checks.append(("source descriptors", not issues, f"{len(descs)} files, {len(issues)} issues"))

    table = Table(title="openquyhoach doctor")
    table.add_column("check")
    table.add_column("status")
    table.add_column("detail")
    ok_all = True
    for name, ok, detail in checks:
        ok_all = ok_all and ok
        table.add_row(name, "[green]ok[/]" if ok else "[red]FAIL[/]", detail)
    console.print(table)
    raise typer.Exit(0 if ok_all else 1)


# ---------------------------------------------------------------- sources


@sources_app.command("list")
def sources_list(json_out: bool = typer.Option(False, "--json")):
    from openquyhoach_ingest.sources import iter_descriptors, load_descriptor

    rows = []
    for p in iter_descriptors():
        d = load_descriptor(p)
        rows.append(
            {
                "key": d.get("key"),
                "name": d.get("name"),
                "type": d.get("source_type"),
                "jurisdiction": d.get("jurisdiction"),
                "enabled": d.get("enabled", True),
                "path": str(p),
            }
        )
    if json_out:
        console.print_json(json.dumps(rows, ensure_ascii=False))
        return
    table = Table(title="Configured sources")
    for c in ("key", "name", "type", "jurisdiction", "enabled"):
        table.add_column(c)
    for r in rows:
        table.add_row(*(str(r[c]) for c in ("key", "name", "type", "jurisdiction", "enabled")))
    console.print(table)


@sources_app.command("validate")
def sources_validate():
    from openquyhoach_ingest.sources import validate_all

    issues = validate_all()
    if not issues:
        console.print("[green]all source descriptors valid[/]")
        raise typer.Exit(0)
    for i in issues:
        err.print(f"[red]{i.path}[/]: {i.message}")
    raise typer.Exit(1)


@sources_app.command("inspect")
def sources_inspect(key: str):
    from openquyhoach_ingest.sources import load_config

    cfg = load_config(key)
    console.print_json(
        json.dumps(
            {
                "key": cfg.key,
                "name": cfg.name,
                "source_type": cfg.source_type,
                "base_url": cfg.base_url,
                "discovery": cfg.discovery,
                "parser": cfg.parser,
                "crawl_policy": cfg.crawl_policy,
                "allowed_formats": cfg.allowed_formats,
                "jurisdiction": cfg.jurisdiction,
                "authority": cfg.authority,
                "rights": cfg.rights,
                "enabled": cfg.enabled,
            },
            ensure_ascii=False,
            default=str,
        )
    )


@sources_app.command("sync")
def sources_sync(
    key: str | None = typer.Argument(None, help="crawl a single source key"),
    limit: int | None = typer.Option(None, "--limit"),
    download: bool = typer.Option(True, "--download/--no-download"),
):
    """With a key: run one crawl cycle for that source (observe + fetch +
    change detection). Without: upsert all descriptors into the database."""
    if key is None:
        from openquyhoach_ingest.sources import sync_sources

        console.print_json(json.dumps(sync_sources(), ensure_ascii=False))
        return
    from openquyhoach_ingest.crawl import sync_source

    run_id = sync_source(key, trigger="cli", limit=limit, download=download)
    console.print(f"run_id={run_id}")


@sources_app.command("sync-all")
def sources_sync_all(limit: int | None = typer.Option(None, "--limit")):
    """Run one crawl cycle for every enabled source, in priority order."""
    from openquyhoach_core.db import session_scope
    from openquyhoach_core.models import Source
    from openquyhoach_ingest.crawl import sync_source

    with session_scope() as s:
        keys = [
            k
            for (k,) in s.query(Source.source_key)
            .filter(Source.enabled.is_(True))
            .order_by(Source.priority.asc(), Source.id.asc())
            .all()
        ]
    results = {}
    for k in keys:
        try:
            results[k] = str(sync_source(k, trigger="cli", limit=limit))
        except Exception as exc:
            results[k] = f"error: {exc}"
    console.print_json(json.dumps(results, ensure_ascii=False))


@sources_app.command("discover")
def sources_discover(key: str, limit: int | None = typer.Option(None, "--limit")):
    """Discovery-only observation: refresh the resource inventory, no fetch."""
    from openquyhoach_ingest.crawl import sync_source

    run_id = sync_source(key, trigger="cli", limit=limit, download=False)
    console.print(f"run_id={run_id}")


@sources_app.command("status")
def sources_status(json_out: bool = typer.Option(False, "--json")):
    """Per-source crawl state: health, freshness, failures, next check."""
    from openquyhoach_core.db import session_scope
    from openquyhoach_core.models import Source, SourceCrawlState

    with session_scope() as s:
        rows = (
            s.query(Source, SourceCrawlState)
            .outerjoin(SourceCrawlState, SourceCrawlState.source_id == Source.id)
            .order_by(Source.priority.asc(), Source.id.asc())
            .all()
        )
        payload = [
            {
                "key": src.source_key,
                "enabled": src.enabled,
                "health": st.health if st else "unknown",
                "last_check": str(st.last_check_at) if st and st.last_check_at else None,
                "last_success": str(st.last_success_at) if st and st.last_success_at else None,
                "last_change": str(st.last_change_at) if st and st.last_change_at else None,
                "next_check": str(st.next_check_at) if st and st.next_check_at else None,
                "failures": st.consecutive_failures if st else 0,
                "resources": st.resources_seen if st else 0,
                "error": (st.last_error or "")[:120] if st else None,
            }
            for src, st in rows
        ]
    if json_out:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return
    table = Table(title="Source crawl status")
    for c in ("key", "health", "last_check", "last_change", "next_check", "fails", "res"):
        table.add_column(c)
    for r in payload:
        table.add_row(
            r["key"],
            r["health"],
            (r["last_check"] or "-")[:19],
            (r["last_change"] or "-")[:19],
            (r["next_check"] or "-")[:19],
            str(r["failures"]),
            str(r["resources"]),
        )
    console.print(table)


@sources_app.command("failures")
def sources_failures(limit: int = typer.Option(20, "--limit")):
    """Recent failed runs and error observations across all sources."""
    from openquyhoach_core.db import session_scope
    from openquyhoach_core.enums import ObservationOutcome
    from openquyhoach_core.models import IngestionRun, Source, SourceObservation

    with session_scope() as s:
        runs = (
            s.query(IngestionRun, Source.source_key)
            .join(Source, Source.id == IngestionRun.source_id)
            .filter(IngestionRun.status.in_(["failed", "partial"]))
            .order_by(IngestionRun.started_at.desc())
            .limit(limit)
            .all()
        )
        obs = (
            s.query(SourceObservation, Source.source_key)
            .join(Source, Source.id == SourceObservation.source_id)
            .filter(SourceObservation.outcome == ObservationOutcome.error.value)
            .order_by(SourceObservation.observed_at.desc())
            .limit(limit)
            .all()
        )
        console.print_json(
            json.dumps(
                {
                    "failed_runs": [
                        {
                            "run": str(r.id),
                            "source": k,
                            "status": r.status,
                            "at": str(r.started_at),
                            "error": (r.error_summary or "")[:200],
                        }
                        for r, k in runs
                    ],
                    "error_observations": [
                        {
                            "source": k,
                            "at": str(o.observed_at),
                            "http_status": o.http_status,
                            "detail": o.detail,
                        }
                        for o, k in obs
                    ],
                },
                ensure_ascii=False,
                default=str,
            )
        )


# ---------------------------------------------------------------- ingest


@ingest_app.command("file")
def ingest_file(
    path: Path = typer.Argument(..., exists=True),  # noqa: B008 - typer idiom
    source: str | None = typer.Option(None, "--source", "-s"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    from openquyhoach_ingest.pipeline import ingest_path

    run_id = ingest_path(path, source_key=source, dry_run=dry_run)
    console.print(f"run_id={run_id}")


@ingest_app.command("url")
def ingest_url_cmd(
    url: str,
    source: str | None = typer.Option(None, "--source", "-s"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    from openquyhoach_ingest.pipeline import ingest_url

    run_id = ingest_url(url, source_key=source, dry_run=dry_run)
    console.print(f"run_id={run_id}")


@ingest_app.command("source")
def ingest_source_cmd(
    key: str,
    dry_run: bool = typer.Option(False, "--dry-run"),
    limit: int | None = typer.Option(None, "--limit"),
):
    from openquyhoach_ingest.pipeline import ingest_source

    run_id = ingest_source(key, dry_run=dry_run, limit=limit)
    console.print(f"run_id={run_id}")


@ingest_app.command("inspect")
def ingest_inspect(run_id: str):
    from openquyhoach_core.db import session_scope
    from openquyhoach_core.models import IngestionRun, ProvenanceEvent

    with session_scope() as s:
        run = s.get(IngestionRun, uuid.UUID(run_id))
        if run is None:
            err.print(f"run {run_id} not found")
            raise typer.Exit(1)
        events = (
            s.query(ProvenanceEvent)
            .filter(ProvenanceEvent.run_id == run.id)
            .order_by(ProvenanceEvent.created_at)
            .all()
        )
        console.print_json(
            json.dumps(
                {
                    "id": str(run.id),
                    "status": run.status,
                    "started_at": str(run.started_at),
                    "completed_at": str(run.completed_at),
                    "discovered": run.discovered_count,
                    "downloaded": run.downloaded_count,
                    "imported": run.imported_count,
                    "rejected": run.rejected_count,
                    "warnings": run.warning_count,
                    "error": run.error_summary,
                    "events": [
                        {
                            "operation": e.operation,
                            "entity": f"{e.entity_type}:{e.entity_id}",
                            "tool": e.tool,
                            "at": str(e.created_at),
                        }
                        for e in events
                    ],
                },
                ensure_ascii=False,
                default=str,
            )
        )


@ingest_app.command("retry")
def ingest_retry(run_id: str):
    """Retry a failed run — stages already completed are skipped (idempotent)."""
    from openquyhoach_core.db import session_scope
    from openquyhoach_core.models import IngestionRun, Source
    from openquyhoach_ingest.pipeline import ingest_source

    with session_scope() as s:
        run = s.get(IngestionRun, uuid.UUID(run_id))
        if run is None:
            err.print(f"run {run_id} not found")
            raise typer.Exit(1)
        source = s.get(Source, run.source_id) if run.source_id else None
    if source is None:
        err.print("run has no source — cannot retry")
        raise typer.Exit(1)
    new_run = ingest_source(source.source_key)
    console.print(f"run_id={new_run}")


# ---------------------------------------------------------------- validate


@app.command()
def validate(
    path: Path = typer.Argument(..., exists=True, help="vector file to validate"),  # noqa: B008 - typer idiom
    json_out: bool = typer.Option(False, "--json"),
    only: str | None = typer.Option(None, "--only", help="comma-separated rule codes"),
    skip: str | None = typer.Option(None, "--skip"),
):
    """Validate a vector dataset file against the rule catalog."""
    from openquyhoach_geo.vector import iter_features, list_layers
    from openquyhoach_quality.engine import (
        FeaturePayload,
        LayerPayload,
        ValidationContext,
        report_json,
        report_text,
        run_rules,
        summarize,
    )

    layers_payload: list[LayerPayload] = []
    crs = None
    for info in list_layers(path):
        if crs is None:
            crs = info.crs
        feats = [
            FeaturePayload(
                key=str(f.fid) if f.fid is not None else None,
                geometry=f.geometry,
                properties=f.properties,
            )
            for f in iter_features(path, info.name)
        ]
        layers_payload.append(
            LayerPayload(
                name=info.name,
                geometry_type=info.geometry_type,
                expected_geometry_type=None,
                features=feats,
            )
        )
    ctx = ValidationContext(
        dataset_id=None,
        original_crs=(crs.to_json() if crs else {}),
        layers=layers_payload,
    )
    findings = run_rules(
        ctx,
        only=[c.strip() for c in only.split(",")] if only else None,
        skip=[c.strip() for c in skip.split(",")] if skip else None,
    )
    if json_out:
        console.print(report_json(findings))
    else:
        console.print(report_text(findings))
    raise typer.Exit(1 if summarize(findings)["has_errors"] else 0)


# ---------------------------------------------------------------- publish


@app.command()
def publish(
    version_id: str,
    max_zoom: int = typer.Option(14, "--max-zoom"),
    allow_unreviewed: bool = typer.Option(False, "--allow-unreviewed"),
):
    """Publish an immutable PMTiles snapshot + manifest for a planning version."""
    from openquyhoach_services.publish import publish_version

    pub_id = publish_version(
        uuid.UUID(version_id), max_zoom=max_zoom, allow_unreviewed=allow_unreviewed
    )
    console.print(f"publication_id={pub_id}")


# ---------------------------------------------------------------- compare


@app.command()
def compare(from_layer: str, to_layer: str, json_out: bool = typer.Option(False, "--json")):
    """Compute (or reuse) a ChangeSet between two layers."""
    from openquyhoach_services.compare import compute_changeset

    cs_id = compute_changeset(uuid.UUID(from_layer), uuid.UUID(to_layer))
    from openquyhoach_core.db import session_scope
    from openquyhoach_core.models import ChangeSet

    with session_scope() as s:
        cs = s.get(ChangeSet, cs_id)
        if cs is None:
            raise SystemExit(f"changeset {cs_id} not found")
        payload = {"change_set_id": str(cs.id), "summary": cs.summary}
    console.print_json(json.dumps(payload, ensure_ascii=False)) if json_out else console.print(
        payload
    )


# ---------------------------------------------------------------- db


@db_app.command("check")
def db_check():
    """Verify DB connectivity and PostGIS."""
    from openquyhoach_core.db import get_engine
    from sqlalchemy import text

    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
        v = conn.execute(text("SELECT PostGIS_Version()")).scalar()
    console.print(f"[green]ok[/] postgis={v}")


@db_app.command("init")
def db_init():
    """Create extensions + apply migrations."""
    import subprocess

    from openquyhoach_core.db import get_engine
    from sqlalchemy import text

    with get_engine().connect() as conn:
        for ext in ("postgis", "unaccent", "pg_trgm"):
            conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext}"))
        sql = Path("db/functions/vn_normalize.sql").read_text(encoding="utf-8")
        conn.execute(text(sql))
        conn.commit()
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "db/alembic.ini", "upgrade", "head"],
        check=True,
    )
    console.print("[green]db initialised[/]")


@db_app.command("seed")
def db_seed(demo: bool = typer.Option(False, "--demo")):
    """Seed the synthetic DemoDistrict dataset (never real data)."""
    if not demo:
        err.print("seed only supports --demo (synthetic fixtures) for now")
        raise typer.Exit(1)
    from scripts.seed_demo import seed

    seed()
    console.print("[green]demo data seeded[/]")


# ---------------------------------------------------------------- coverage


@app.command()
def coverage(
    recompute: bool = typer.Option(False, "--recompute"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Coverage + freshness per administrative unit."""
    if recompute:
        from openquyhoach_services.coverage import recompute_coverage

        n = recompute_coverage()
        console.print(f"recomputed {n} coverage rows")
    from openquyhoach_core.db import session_scope
    from openquyhoach_core.models import AdministrativeUnit, CoverageSummary

    with session_scope() as s:
        rows = (
            s.query(CoverageSummary, AdministrativeUnit)
            .join(AdministrativeUnit, AdministrativeUnit.id == CoverageSummary.admin_unit_id)
            .all()
        )
        payload = [
            {
                "unit": u.name,
                "official_code": u.official_code,
                "level": u.level,
                "state": c.state,
                "sources": c.source_count,
                "documents": c.document_count,
                "datasets": c.dataset_count,
                "reviewed": c.reviewed_count,
                "last_checked": str(c.last_checked) if c.last_checked else None,
            }
            for c, u in rows
        ]
    if json_out:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return
    table = Table(title="Coverage")
    for c in ("unit", "code", "level", "state", "src", "docs", "data", "rev"):
        table.add_column(c)
    for r in payload:
        table.add_row(
            r["unit"],
            r["official_code"] or "-",
            str(r["level"] or "-"),
            r["state"],
            str(r["sources"]),
            str(r["documents"]),
            str(r["datasets"]),
            str(r["reviewed"]),
        )
    console.print(table)


# ---------------------------------------------------------------- changes


@changes_app.command("recent")
def changes_recent(
    source: str | None = typer.Option(None, "--source"),
    limit: int = typer.Option(50, "--limit"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Recent upstream change events (added/disappeared/checksum/url/meta)."""
    from openquyhoach_core.db import session_scope
    from openquyhoach_core.models import Source, SourceChangeEvent

    with session_scope() as s:
        q = (
            s.query(SourceChangeEvent, Source.source_key)
            .join(Source, Source.id == SourceChangeEvent.source_id)
            .order_by(SourceChangeEvent.detected_at.desc())
            .limit(limit)
        )
        if source:
            q = q.filter(Source.source_key == source)
        rows = [
            {
                "source": k,
                "type": e.change_type,
                "at": str(e.detected_at),
                "resource": str(e.resource_id) if e.resource_id else None,
                "detail": e.detail,
            }
            for e, k in q.all()
        ]
    if json_out:
        console.print_json(json.dumps(rows, ensure_ascii=False))
        return
    table = Table(title="Recent upstream changes")
    for c in ("at", "source", "type", "detail"):
        table.add_column(c)
    for r in rows:
        table.add_row(r["at"][:19], r["source"], r["type"], json.dumps(r["detail"])[:80])
    console.print(table)


# ---------------------------------------------------------------- scheduler


@scheduler_app.command("tick")
def scheduler_tick_cmd(limit: int = typer.Option(20, "--limit")):
    """Enqueue sync jobs for all due sources (one scheduling pass)."""
    from openquyhoach_ingest.scheduler import scheduler_tick

    console.print_json(json.dumps(scheduler_tick(tick_limit=limit), ensure_ascii=False))


@scheduler_app.command("loop")
def scheduler_loop_cmd(
    interval: int = typer.Option(60, "--interval"),
    once: bool = typer.Option(False, "--once"),
):
    """Run the scheduler continuously (cron/systemd alternative)."""
    from openquyhoach_ingest.scheduler import scheduler_loop

    scheduler_loop(interval_s=interval, once=once)


def main():  # console_scripts entry
    app()


if __name__ == "__main__":
    main()
