"""Connector contract.

Lifecycle (spec §9):

    discover(source) -> Iterable[DiscoveredItem]   # find candidate artifacts
    fetch(item)      -> FetchResult                # immutable bytes on disk
    inspect(result)  -> dict                       # cheap structure probe
    normalize/emit   -> handled by the pipeline per detected format

Connectors never write to the database — the pipeline owns persistence.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from openquyhoach_core.errors import UnsupportedFormatError


@dataclass
class SourceConfig:
    """A validated source descriptor (see sources/_schema)."""

    key: str
    name: str
    source_type: str
    base_url: str | None = None
    discovery: dict = field(default_factory=dict)
    parser: dict = field(default_factory=dict)
    crawl_policy: dict = field(default_factory=dict)
    allowed_formats: list[str] = field(default_factory=list)
    jurisdiction: str | None = None
    authority: str | None = None
    rights: dict = field(default_factory=dict)
    enabled: bool = True
    meta: dict = field(default_factory=dict)


@dataclass
class DiscoveredItem:
    """Something a source offers for download."""

    url: str  # canonical location (https:// or file://)
    suggested_filename: str | None = None
    metadata: dict = field(default_factory=dict)  # title, date, ids, layer hints...
    etag: str | None = None
    last_modified: str | None = None


@dataclass
class FetchResult:
    """Bytes on local disk + identity metadata. The pipeline stores them
    content-addressed afterwards."""

    local_path: Path
    canonical_url: str
    retrieved_url: str
    sha256: str
    size: int
    mime_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False  # conditional request said cache hit
    filename: str | None = None  # display name from discovery (local_path may be a tempfile)


@runtime_checkable
class Connector(Protocol):
    source_type: str

    def discover(self, source: SourceConfig) -> Iterable[DiscoveredItem]: ...
    def fetch(self, source: SourceConfig, item: DiscoveredItem, workdir: Path) -> FetchResult: ...
    def inspect(self, result: FetchResult) -> dict[str, Any]: ...


_REGISTRY: dict[str, Connector] = {}


def register(connector: Connector) -> None:
    _REGISTRY[connector.source_type] = connector


def get_connector(source_type: str) -> Connector:
    try:
        return _REGISTRY[source_type]
    except KeyError:
        raise UnsupportedFormatError(f"no connector for source_type {source_type!r}") from None
