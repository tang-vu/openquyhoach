"""Provenance recording — one entry point so every event is shaped the same."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from .enums import ActorType, ProvenanceOp
from .models.ops import ProvenanceEvent


def record_event(
    session: Session,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    operation: str | ProvenanceOp,
    input_refs: list[dict[str, Any]] | None = None,
    tool: str | None = None,
    tool_version: str | None = None,
    model: str | None = None,
    parameters: dict[str, Any] | None = None,
    output_hash: str | None = None,
    actor_type: str | ActorType = ActorType.SYSTEM,
    actor: str | None = None,
    run_id: uuid.UUID | None = None,
) -> ProvenanceEvent:
    ev = ProvenanceEvent(
        entity_type=entity_type,
        entity_id=entity_id,
        operation=str(operation),
        input_refs=input_refs or [],
        tool=tool,
        tool_version=tool_version,
        model=model,
        parameters=parameters or {},
        output_hash=output_hash,
        actor_type=str(actor_type),
        actor=actor,
        run_id=run_id,
    )
    session.add(ev)
    return ev
