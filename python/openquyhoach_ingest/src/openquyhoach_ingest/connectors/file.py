"""Local file/folder connector — the community-import and test path."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path

from openquyhoach_core.hashing import sha256_file
from openquyhoach_core.security import sniff_format

from .base import DiscoveredItem, FetchResult, SourceConfig, register

DEFAULT_GLOBS = [
    "*.gpkg",
    "*.geojson",
    "*.json",
    "*.shp",
    "*.kml",
    "*.dxf",
    "*.dwg",
    "*.tif",
    "*.tiff",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.pdf",
    "*.zip",
    "*.fgb",
]


class FileConnector:
    source_type = "file"

    @staticmethod
    def _root(source: SourceConfig) -> Path:
        # file://host/path and file:///abs/path both collapse to a plain path;
        # a bare relative path is resolved against the process CWD.
        raw = source.discovery.get("path") or (source.base_url or ".")
        return Path(raw.removeprefix("file://"))

    def discover(self, source: SourceConfig) -> Iterable[DiscoveredItem]:
        root = self._root(source)
        if root.is_file():
            yield DiscoveredItem(url=root.resolve().as_uri(), suggested_filename=root.name)
            return
        globs = source.discovery.get("globs") or DEFAULT_GLOBS
        for pattern in globs:
            for path in sorted(root.rglob(pattern)):
                if path.is_file():
                    yield DiscoveredItem(
                        url=path.resolve().as_uri(),
                        suggested_filename=path.name,
                        metadata={"path": str(path)},
                    )

    def fetch(self, source: SourceConfig, item: DiscoveredItem, workdir: Path) -> FetchResult:
        path = Path(item.url.replace("file://", ""))
        workdir.mkdir(parents=True, exist_ok=True)
        # keep the extension: GDAL drivers sniff by suffix as well as content
        suffix = path.suffix or ""
        tmp = Path(tempfile.mkstemp(dir=workdir, prefix="file-", suffix=suffix)[1])
        shutil.copyfile(path, tmp)
        sha, size = sha256_file(tmp)
        return FetchResult(
            local_path=tmp,
            canonical_url=item.url,
            retrieved_url=item.url,
            sha256=sha,
            size=size,
            mime_type=None,
            etag=None,
            last_modified=None,
        )

    def inspect(self, result: FetchResult) -> dict:
        head = result.local_path.read_bytes()[:512]
        return {"detected_format": sniff_format(head, result.local_path.name)}


register(FileConnector())
