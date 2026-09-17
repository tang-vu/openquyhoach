"""Shared API dependencies: pagination + admin guard."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query
from openquyhoach_core.settings import get_settings


@dataclass
class Page:
    limit: int
    offset: int


def pagination(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page:
    return Page(limit=limit, offset=offset)


PageDep = Annotated[Page, Depends(pagination)]


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    """Mutating endpoints require the configured admin token.

    If the operator leaves the default dev token, we still enforce the
    header — callers must send it explicitly. Production deployments must
    override OQH_ADMIN_TOKEN via env.
    """
    expected = get_settings().admin_token
    if not x_admin_key or not secrets.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=403, detail="admin key required")


AdminGuard = Depends(require_admin)
