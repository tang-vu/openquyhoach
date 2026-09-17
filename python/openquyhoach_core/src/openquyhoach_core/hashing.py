"""Content hashing helpers — everything content-addressed goes through here."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import BinaryIO

_CHUNK = 1024 * 1024


def sha256_stream(stream: BinaryIO, *, limit: int | None = None) -> tuple[str, int]:
    """Return (hexdigest, bytes_read). Stops at `limit` if set."""
    h = hashlib.sha256()
    total = 0
    while True:
        chunk = stream.read(_CHUNK)
        if not chunk:
            break
        h.update(chunk)
        total += len(chunk)
        if limit is not None and total > limit:
            raise ValueError(f"stream exceeds limit of {limit} bytes")
    return h.hexdigest(), total


def sha256_file(path: str | Path) -> tuple[str, int]:
    with open(path, "rb") as fh:
        return sha256_stream(fh)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class HashingReader(io.RawIOBase):
    """Wrap a stream and compute sha256 while it is consumed."""

    def __init__(self, raw: BinaryIO):
        self._raw = raw
        self._h = hashlib.sha256()
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:  # type: ignore[override]
        data = self._raw.read(size)
        self._h.update(data)
        self.bytes_read += len(data)
        return data

    def readable(self) -> bool:
        return True

    @property
    def hexdigest(self) -> str:
        return self._h.hexdigest()
