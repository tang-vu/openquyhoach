"""Shared pytest fixtures.

Unit tests run with zero infrastructure. Tests marked ``integration``
need the docker-compose stack (PostGIS + MinIO) and use a dedicated
``openquyhoach_test`` database that is migrated once per session and
truncated between tests.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # for `scripts.*` helpers

FIXTURES = ROOT / "fixtures" / "synthetic" / "demo_district"


def _db_url() -> str:
    return os.environ.get(
        "OQH_DATABASE_URL",
        "postgresql+psycopg://oqh:oqh@localhost:5432/openquyhoach_test",
    )


def _db_available(url: str) -> bool:
    try:
        import psycopg

        with psycopg.connect(url.replace("+psycopg", ""), connect_timeout=3):
            return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def integration_db():
    """Migrated test database; yields the DSN. Skips when DB unreachable."""
    url = _db_url()
    if not _db_available(url):
        pytest.skip("PostGIS test database not reachable")
    # Repoint the in-process engine at the test DB *before* migrating, so
    # tests can never touch the development database.
    os.environ["OQH_DATABASE_URL"] = url
    from openquyhoach_core.db import get_engine, reset_engine
    from openquyhoach_core.settings import get_settings

    get_settings.cache_clear()
    reset_engine()
    get_engine(url)
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "db/alembic.ini", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "OQH_DATABASE_URL": url},
        check=True,
        capture_output=True,
    )
    yield url
    reset_engine()


@pytest.fixture()
def db(integration_db):
    """Clean-database fixture: truncates all domain tables per test."""
    from openquyhoach_core.db import get_engine
    from sqlalchemy import text

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE ingestion_runs, source_artifacts, provenance_events,"
                " datasets, layers, features, planning_records,"
                " planning_versions, documents, review_tasks,"
                " quality_observations, administrative_units,"
                " georeference_jobs, publications, change_sets,"
                " change_set_entries, coverage_summaries, sources CASCADE"
            )
        )
    return engine


@pytest.fixture()
def local_store(tmp_path):
    """Redirect object storage to a local dir — no MinIO needed."""
    from openquyhoach_core.storage import LocalStore, reset_stores, set_stores

    store = LocalStore(tmp_path / "store")
    set_stores(store)
    yield tmp_path / "store"
    reset_stores()
