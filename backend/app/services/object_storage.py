from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Protocol

try:  # pragma: no cover - import availability is environment-dependent
    from minio import Minio
except Exception:  # pragma: no cover
    Minio = None  # type: ignore[assignment]


class ObjectStorageError(RuntimeError):
    pass


class ObjectStorage(Protocol):
    def upload_file(self, *, bucket_name: str, object_key: str, path: Path, content_type: str | None = None) -> None:
        """Upload a local file to object storage."""


def build_asset_object_key(*, asset_code: str, filename: str, file_role: str = "original") -> str:
    safe_name = filename.replace("\\", "_").replace("/", "_")
    return f"assets/{asset_code}/{file_role}/{safe_name}"


def content_type_for_path(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


class MinioObjectStorage:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool = False,
    ) -> None:
        if Minio is None:
            raise ObjectStorageError("minio package is not installed")
        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)

    def ensure_bucket(self, bucket_name: str) -> None:
        if not self.client.bucket_exists(bucket_name):
            self.client.make_bucket(bucket_name)

    def upload_file(self, *, bucket_name: str, object_key: str, path: Path, content_type: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            raise ObjectStorageError(f"file does not exist: {path}")
        self.ensure_bucket(bucket_name)
        self.client.fput_object(
            bucket_name,
            object_key,
            str(path),
            content_type=content_type or content_type_for_path(path),
        )
