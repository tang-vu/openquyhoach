"""Object storage abstraction.

`ObjectStore` protocol with two backends:

* ``S3Store`` — boto3 against any S3-compatible endpoint (MinIO locally,
  S3/R2/etc in production).
* ``LocalStore`` — filesystem, used by tests and offline tooling.

Artifacts are stored under content-addressed keys:
``sha256/<first2>/<full-sha256>/<safe-filename>``.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable

from .settings import Settings, get_settings

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(name: str | None, default: str = "artifact") -> str:
    """Strip path separators/control chars; never allow traversal."""
    if not name:
        return default
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip().strip(".")
    base = _SAFE.sub("_", base)[:180]
    return base or default


def artifact_key(sha256: str, filename: str | None) -> str:
    return f"sha256/{sha256[:2]}/{sha256}/{sanitize_filename(filename)}"


@runtime_checkable
class ObjectStore(Protocol):
    def put(self, key: str, data: BinaryIO | bytes, *, content_type: str | None = None) -> str: ...
    def get(self, key: str) -> bytes: ...
    def open(self, key: str) -> BinaryIO: ...
    def exists(self, key: str) -> bool: ...
    def size(self, key: str) -> int | None: ...
    def presigned_url(self, key: str, expires: int = 3600) -> str: ...
    def get_range(self, key: str, start: int, end: int) -> bytes: ...


class S3Store:
    def __init__(self, settings: Settings | None = None, bucket: str | None = None):
        import boto3
        from botocore.config import Config

        s = settings or get_settings()
        self.bucket = bucket or s.s3_bucket_artifacts
        self._s3 = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint,
            region_name=s.s3_region,
            aws_access_key_id=s.s3_access_key,
            aws_secret_access_key=s.s3_secret_key,
            config=Config(signature_version="s3v4"),
            use_ssl=s.s3_secure,
        )

    def ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self._s3.head_bucket(Bucket=self.bucket)
        except ClientError:
            self._s3.create_bucket(Bucket=self.bucket)

    def put(self, key: str, data: BinaryIO | bytes, *, content_type: str | None = None) -> str:
        extra = {"ContentType": content_type} if content_type else {}
        if isinstance(data, (bytes, bytearray)):
            self._s3.put_object(Bucket=self.bucket, Key=key, Body=bytes(data), **extra)
        else:
            self._s3.upload_fileobj(data, self.bucket, key, ExtraArgs=extra or None)
        return key

    def get(self, key: str) -> bytes:
        return self._s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def open(self, key: str) -> BinaryIO:
        return self._s3.get_object(Bucket=self.bucket, Key=key)["Body"]

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def size(self, key: str) -> int | None:
        try:
            return self._s3.head_object(Bucket=self.bucket, Key=key)["ContentLength"]
        except Exception:
            return None

    def presigned_url(self, key: str, expires: int = 3600) -> str:
        return self._s3.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires
        )

    def get_range(self, key: str, start: int, end: int) -> bytes:
        return self._s3.get_object(Bucket=self.bucket, Key=key, Range=f"bytes={start}-{end}")[
            "Body"
        ].read()

    def public_url(self, key: str) -> str:
        return f"{self._s3.meta.endpoint_url}/{self.bucket}/{key}"


class LocalStore:
    """Filesystem-backed store for tests and offline work."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        key = key.lstrip("/")
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents and path != self.root.resolve():
            raise ValueError(f"key escapes store root: {key!r}")
        return path

    def put(self, key: str, data: BinaryIO | bytes, *, content_type: str | None = None) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, (bytes, bytearray)):
            path.write_bytes(bytes(data))
        else:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
                shutil.copyfileobj(data, tmp)
            os.replace(tmp.name, path)
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def open(self, key: str) -> BinaryIO:
        return io.BytesIO(self.get(key))

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def size(self, key: str) -> int | None:
        p = self._path(key)
        return p.stat().st_size if p.exists() else None

    def presigned_url(self, key: str, expires: int = 3600) -> str:
        return f"file://{self._path(key)}"

    def get_range(self, key: str, start: int, end: int) -> bytes:
        with open(self._path(key), "rb") as fh:
            fh.seek(start)
            return fh.read(end - start + 1)

    def fs_path(self, key: str) -> Path:
        """Real path — lets GDAL read COGs without a copy in local dev/tests."""
        return self._path(key)


_artifacts: ObjectStore | None = None
_published: ObjectStore | None = None


def artifact_store() -> ObjectStore:
    global _artifacts
    if _artifacts is None:
        _artifacts = S3Store(bucket=get_settings().s3_bucket_artifacts)
    return _artifacts


def published_store() -> ObjectStore:
    global _published
    if _published is None:
        _published = S3Store(bucket=get_settings().s3_bucket_published)
    return _published


def set_stores(artifacts: ObjectStore, published: ObjectStore | None = None) -> None:
    """Test/CLI hook to inject alternate backends."""
    global _artifacts, _published
    _artifacts = artifacts
    _published = published or artifacts


def reset_stores() -> None:
    """Drop injected backends — next access rebuilds from settings."""
    global _artifacts, _published
    _artifacts = None
    _published = None
