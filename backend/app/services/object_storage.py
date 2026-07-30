from __future__ import annotations

import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Protocol

try:  # pragma: no cover - import availability is environment-dependent
    from minio import Minio
    from minio.commonconfig import ENABLED
    from minio.error import S3Error
    from minio.versioningconfig import VersioningConfig
except Exception:  # pragma: no cover
    Minio = None  # type: ignore[assignment]
    ENABLED = None  # type: ignore[assignment]
    S3Error = Exception  # type: ignore[assignment,misc]
    VersioningConfig = None  # type: ignore[assignment]


class ObjectStorageError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    object_key: str
    byte_size: int
    checksum_sha256: str | None
    version_id: str | None


class ObjectStorage(Protocol):
    def upload_file(
        self,
        *,
        bucket_name: str,
        object_key: str,
        path: Path,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        """Upload a local file to object storage."""

    def download_file(
        self,
        *,
        bucket_name: str,
        object_key: str,
        destination: Path,
    ) -> None:
        """Download an object to a caller-owned temporary path."""


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

    def ensure_versioned_bucket(self, bucket_name: str) -> None:
        self.ensure_bucket(bucket_name)
        if VersioningConfig is None or ENABLED is None:  # pragma: no cover
            raise ObjectStorageError("minio versioning support is unavailable")
        self.client.set_bucket_versioning(bucket_name, VersioningConfig(ENABLED))

    def stat_object(self, *, bucket_name: str, object_key: str) -> ObjectMetadata | None:
        try:
            stat: Any = self.client.stat_object(bucket_name, object_key)
        except S3Error as exc:
            if getattr(exc, "code", None) in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                return None
            raise ObjectStorageError(f"unable to stat object: {object_key}") from exc
        metadata = getattr(stat, "metadata", {}) or {}
        checksum = metadata.get("x-amz-meta-sha256") or metadata.get("sha256")
        return ObjectMetadata(
            object_key=object_key,
            byte_size=int(stat.size),
            checksum_sha256=str(checksum) if checksum else None,
            version_id=str(stat.version_id) if getattr(stat, "version_id", None) else None,
        )

    def upload_file(
        self,
        *,
        bucket_name: str,
        object_key: str,
        path: Path,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        if not path.exists() or not path.is_file():
            raise ObjectStorageError(f"file does not exist: {path}")
        self.ensure_bucket(bucket_name)
        try:
            self.client.fput_object(
                bucket_name,
                object_key,
                str(path),
                content_type=content_type or content_type_for_path(path),
                metadata=metadata,
            )
        except Exception as exc:  # MinIO client errors vary by transport/runtime.
            raise ObjectStorageError(f"unable to upload object: {object_key}") from exc

    def download_file(
        self,
        *,
        bucket_name: str,
        object_key: str,
        destination: Path,
    ) -> None:
        try:
            self.client.fget_object(bucket_name, object_key, str(destination))
        except Exception as exc:  # MinIO client errors vary by transport/runtime.
            raise ObjectStorageError(f"unable to download object: {object_key}") from exc


class LocalObjectStorage:
    """Small filesystem object store for local deployments without MinIO."""

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()

    def _object_path(self, bucket_name: str, object_key: str) -> Path:
        bucket = PurePosixPath(bucket_name)
        key = PurePosixPath(object_key.replace("\\", "/"))
        if (
            not bucket.parts
            or bucket.is_absolute()
            or ".." in bucket.parts
            or not key.parts
            or key.is_absolute()
            or ".." in key.parts
        ):
            raise ObjectStorageError("invalid local object path")
        candidate = (self.root / Path(*bucket.parts) / Path(*key.parts)).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ObjectStorageError("invalid local object path") from exc
        return candidate

    def upload_file(
        self,
        *,
        bucket_name: str,
        object_key: str,
        path: Path,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        if not path.exists() or not path.is_file():
            raise ObjectStorageError(f"file does not exist: {path}")
        destination = self._object_path(bucket_name, object_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)

    def download_file(self, *, bucket_name: str, object_key: str, destination: Path) -> None:
        source = self._object_path(bucket_name, object_key)
        if not source.is_file():
            raise ObjectStorageError(f"object does not exist: {object_key}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


class ResilientObjectStorage:
    """Prefer MinIO while keeping customer workflows usable on a local-only install."""

    def __init__(self, primary: ObjectStorage, fallback: LocalObjectStorage):
        self.primary = primary
        self.fallback = fallback

    def upload_file(
        self,
        *,
        bucket_name: str,
        object_key: str,
        path: Path,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        try:
            self.primary.upload_file(
                bucket_name=bucket_name,
                object_key=object_key,
                path=path,
                content_type=content_type,
                metadata=metadata,
            )
            return
        except Exception:
            self.fallback.upload_file(
                bucket_name=bucket_name,
                object_key=object_key,
                path=path,
                content_type=content_type,
                metadata=metadata,
            )

    def download_file(self, *, bucket_name: str, object_key: str, destination: Path) -> None:
        try:
            self.primary.download_file(
                bucket_name=bucket_name,
                object_key=object_key,
                destination=destination,
            )
            return
        except Exception:
            self.fallback.download_file(
                bucket_name=bucket_name,
                object_key=object_key,
                destination=destination,
            )
