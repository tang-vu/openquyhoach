"""Engine/session management. Sync SQLAlchemy — pipelines and API share it."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .settings import get_settings

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    if _engine is None or url is not None:
        _engine = create_engine(
            url or get_settings().database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            json_serializer=_json_dumps,
        )
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)

        @event.listens_for(_engine, "connect")
        def _set_search_path(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("SET search_path TO public")
            cur.close()

    return _engine


def _json_dumps(obj):
    import json

    return json.dumps(obj, ensure_ascii=False, default=str)


def session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope — commits on success, rolls back on error."""
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def reset_engine() -> None:
    """Test helper: drop cached engine so a new URL can be used."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
