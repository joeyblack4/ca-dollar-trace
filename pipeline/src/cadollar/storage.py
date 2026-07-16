"""Storage abstraction: local filesystem (dev) or Cloudflare R2 via the S3 API (prod).

Layout (identical in both modes):
  raw/{source}/{dataset}/{as_of}/part-0.parquet
  cleansed/{source}/{dataset}.parquet
  curated/{table}.parquet
  published/{name}.json
  manifest/{source}.json          <- per-source run state (hash, counts, timestamps)

Object puts are atomic per key in both S3/R2 and the local implementation
(write to temp file, then rename), so a failed run never leaves a torn manifest.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Protocol

from .config import Settings

DEFAULT_CT = "application/octet-stream"


class Storage(Protocol):
    def put_bytes(self, key: str, data: bytes, content_type: str = DEFAULT_CT) -> None: ...
    def put_file(self, key: str, path: Path, content_type: str = DEFAULT_CT) -> None: ...
    def get_bytes(self, key: str) -> bytes | None: ...
    def exists(self, key: str) -> bool: ...
    def local_path(self, key: str) -> Path | None:
        """Local filesystem path for a key, if the backend has one (None on R2)."""
        ...


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / key

    def put_bytes(self, key: str, data: bytes, content_type: str = DEFAULT_CT) -> None:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)  # atomic on same filesystem
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def put_file(self, key: str, path: Path, content_type: str = DEFAULT_CT) -> None:
        self.put_bytes(key, path.read_bytes(), content_type)

    def get_bytes(self, key: str) -> bytes | None:
        p = self._path(key)
        return p.read_bytes() if p.exists() else None

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def local_path(self, key: str) -> Path | None:
        return self._path(key)


class R2Storage:
    def __init__(self, settings: Settings):
        import boto3  # deferred: not needed in local mode

        self.bucket = settings.r2_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
        )

    def put_bytes(self, key: str, data: bytes, content_type: str = DEFAULT_CT) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def put_file(self, key: str, path: Path, content_type: str = DEFAULT_CT) -> None:
        self.client.upload_file(
            str(path), self.bucket, key, ExtraArgs={"ContentType": content_type}
        )

    def get_bytes(self, key: str) -> bytes | None:
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=key)
        except self.client.exceptions.NoSuchKey:
            return None
        return resp["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def local_path(self, key: str) -> Path | None:
        return None


def get_storage(settings: Settings) -> Storage:
    if settings.storage_mode == "r2":
        return R2Storage(settings)
    return LocalStorage(settings.data_dir)


# --- Manifests: per-source run state -----------------------------------------


def read_manifest(storage: Storage, source: str) -> dict[str, Any]:
    raw = storage.get_bytes(f"manifest/{source}.json")
    return json.loads(raw) if raw else {}


def write_manifest(storage: Storage, source: str, manifest: dict[str, Any]) -> None:
    storage.put_bytes(
        f"manifest/{source}.json",
        json.dumps(manifest, indent=2, sort_keys=True).encode(),
        content_type="application/json",
    )
