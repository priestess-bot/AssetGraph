from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Protocol

from app.domain.contracts import DataClassification
from app.domain.errors import DomainAuthorizationError, DomainValidationError
from app.services.object_storage import ObjectMetadata, ObjectStorage, content_type_for_path


class ArtifactRepositoryProtocol(Protocol):
    def register_artifact(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_artifact(self, artifact_code: str) -> dict[str, Any] | None: ...


class VersionedObjectStorage(ObjectStorage, Protocol):
    def ensure_versioned_bucket(self, bucket_name: str) -> None: ...

    def stat_object(self, *, bucket_name: str, object_key: str) -> ObjectMetadata | None: ...


class ContentAddressedArtifactService:
    def __init__(
        self,
        repository: ArtifactRepositoryProtocol,
        storage: VersionedObjectStorage,
        *,
        bucket_name: str,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.bucket_name = bucket_name

    def put_file(
        self,
        path: Path,
        *,
        artifact_kind: str,
        schema_version: str,
        producer_type: str,
        producer_code: str,
        producer_revision: int | None,
        sensitivity: DataClassification,
        retention_policy_code: str,
        encryption_key_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not path.is_file():
            raise DomainValidationError("ARTIFACT_SOURCE_NOT_FOUND", "Artifact source file does not exist")
        if sensitivity in {DataClassification.RESTRICTED_PERSONAL, DataClassification.CREDENTIAL} and not encryption_key_ref:
            raise DomainValidationError(
                "ARTIFACT_ENCRYPTION_REQUIRED",
                "Restricted personal and credential artifacts require an encryption key reference",
            )
        digest = hashlib.sha256()
        byte_size = 0
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                byte_size += len(chunk)
        checksum = digest.hexdigest()
        media_type = content_type_for_path(path)
        object_key = f"artifacts/sha256/{checksum[:2]}/{checksum}"
        self.storage.ensure_versioned_bucket(self.bucket_name)
        existing = self.storage.stat_object(bucket_name=self.bucket_name, object_key=object_key)
        if existing is not None:
            if existing.byte_size != byte_size or (
                existing.checksum_sha256 is not None and existing.checksum_sha256 != checksum
            ):
                raise DomainValidationError(
                    "ARTIFACT_CONTENT_ADDRESS_COLLISION",
                    "Existing content-addressed object does not match its expected checksum and size",
                )
        else:
            self.storage.upload_file(
                bucket_name=self.bucket_name,
                object_key=object_key,
                path=path,
                content_type=media_type,
                metadata={"sha256": checksum, "schema-version": schema_version},
            )
        try:
            return self.repository.register_artifact(
                artifact_kind=artifact_kind,
                media_type=media_type,
                schema_version=schema_version,
                storage_uri=f"s3://{self.bucket_name}/{object_key}",
                checksum_sha256=checksum,
                byte_size=byte_size,
                producer_type=producer_type,
                producer_code=producer_code,
                producer_revision=producer_revision,
                sensitivity=sensitivity.value,
                retention_policy_code=retention_policy_code,
                encryption_key_ref=encryption_key_ref,
                metadata=metadata or {},
            )
        except Exception:
            rollback = getattr(self.repository, "rollback", None)
            if callable(rollback):
                rollback()
            raise

    def verify_storage(self, artifact_code: str) -> dict[str, Any]:
        artifact = self.repository.get_artifact(artifact_code)
        if artifact is None:
            raise KeyError(artifact_code)
        prefix = f"s3://{self.bucket_name}/"
        uri = str(artifact["storage_uri"])
        if not uri.startswith(prefix):
            raise DomainValidationError("ARTIFACT_STORAGE_URI_INVALID", "Artifact storage URI is outside its configured bucket")
        object_key = uri.removeprefix(prefix)
        stored = self.storage.stat_object(bucket_name=self.bucket_name, object_key=object_key)
        valid = bool(
            stored
            and stored.byte_size == artifact["byte_size"]
            and (stored.checksum_sha256 is None or stored.checksum_sha256 == artifact["checksum_sha256"])
        )
        return {
            "artifact_code": artifact_code,
            "valid": valid,
            "expected_checksum": artifact["checksum_sha256"],
            "stored_checksum": stored.checksum_sha256 if stored else None,
            "expected_size": artifact["byte_size"],
            "stored_size": stored.byte_size if stored else None,
            "version_id": stored.version_id if stored else None,
        }


def require_artifact_access(
    artifact: dict[str, Any],
    *,
    roles: set[str],
    purpose: str,
) -> None:
    sensitivity = DataClassification(artifact["sensitivity"])
    allowed = {
        DataClassification.PUBLIC: {"read"},
        DataClassification.INTERNAL: {"read", "production", "analysis"},
        DataClassification.CONFIDENTIAL: {"production", "analysis", "audit"},
        DataClassification.RESTRICTED_PERSONAL: {"authorized_analysis", "deletion", "audit"},
        DataClassification.CREDENTIAL: {"credential_rotation"},
    }
    if purpose not in allowed[sensitivity] or not roles.intersection({"operator", "data", "security", "system"}):
        raise DomainAuthorizationError(
            "ARTIFACT_ACCESS_DENIED",
            "Artifact access is not allowed for this role and purpose",
            details={"sensitivity": sensitivity.value, "purpose": purpose},
        )
