from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from uuid import uuid4

from .permissions import require_private_permissions, restrict_private_permissions


class StorageBoundaryError(RuntimeError):
    """A worker path or permission escaped the live-research storage contract."""


class SecureStorage:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        restrict_private_permissions(self.root, 0o700)

    def resolve(self, relative_path: str, *, create_parent: bool = False) -> Path:
        normalized = relative_path.replace("\\", "/")
        relative = PurePosixPath(normalized)
        if relative.is_absolute() or not relative.parts or any(
            part in {"", ".", ".."} for part in relative.parts
        ):
            raise StorageBoundaryError("relative path escapes the live-research root")
        candidate = self.root.joinpath(*relative.parts)
        parent = candidate.parent
        self._require_no_symlink_components(parent)
        if create_parent:
            self._mkdir_secure(parent)
            self._require_no_symlink_components(parent)
        resolved_parent = parent.resolve()
        if not resolved_parent.is_relative_to(self.root):
            raise StorageBoundaryError("relative path resolves outside the live-research root")
        if candidate.exists() and candidate.is_symlink():
            raise StorageBoundaryError("symlinked storage files are not allowed")
        return candidate

    def atomic_write(self, relative_path: str, content: bytes, *, mode: int = 0o600) -> Path:
        if mode != 0o600:
            raise StorageBoundaryError("live-research private files must use mode 0600")
        destination = self.resolve(relative_path, create_parent=True)
        if destination.exists():
            if not destination.is_file() or destination.is_symlink():
                raise StorageBoundaryError("private destination must be a regular file")
            self.require_private_file(destination)
            if destination.stat().st_size == len(content) and _sha256_file(destination) == hashlib.sha256(
                content
            ).hexdigest():
                return destination
            raise StorageBoundaryError("private immutable file already exists with different content")
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.part")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(temporary, flags, mode)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            restrict_private_permissions(temporary, mode)
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if (
                    destination.is_file()
                    and not destination.is_symlink()
                    and destination.stat().st_size == len(content)
                    and _sha256_file(destination) == hashlib.sha256(content).hexdigest()
                ):
                    return destination
                raise StorageBoundaryError(
                    "private immutable file was concurrently created with different content"
                )
            temporary.unlink()
            restrict_private_permissions(destination, mode)
            directory_flag = getattr(os, "O_DIRECTORY", None)
            if directory_flag is not None:
                directory_fd = os.open(destination.parent, os.O_RDONLY | directory_flag)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
        self.require_private_file(destination)
        return destination

    @staticmethod
    def require_private_file(path: Path) -> None:
        try:
            require_private_permissions(path, 0o600)
        except PermissionError as exc:
            raise StorageBoundaryError(str(exc)) from exc

    @staticmethod
    def require_private_config(path: Path) -> None:
        if not path.is_file() or path.is_symlink():
            raise StorageBoundaryError("secret config must be a regular file")
        SecureStorage.require_private_file(path)

    def delete_private_file(
        self,
        relative_path: str,
        *,
        expected_checksum_sha256: str | None = None,
    ) -> bool:
        candidate = self.resolve(relative_path)
        if not candidate.exists():
            return False
        if not candidate.is_file() or candidate.is_symlink():
            raise StorageBoundaryError("retention only deletes regular files")
        if (
            expected_checksum_sha256 is not None
            and _sha256_file(candidate) != expected_checksum_sha256
        ):
            raise StorageBoundaryError("retention candidate checksum changed before deletion")
        candidate.unlink()
        return True

    def _mkdir_secure(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        current = directory
        while current != self.root.parent and current.is_relative_to(self.root):
            if current.is_symlink():
                raise StorageBoundaryError("symlinked storage directories are not allowed")
            restrict_private_permissions(current, 0o700)
            if current == self.root:
                break
            current = current.parent

    def _require_no_symlink_components(self, directory: Path) -> None:
        try:
            relative = directory.relative_to(self.root)
        except ValueError as exc:
            raise StorageBoundaryError("storage parent escapes the live-research root") from exc
        current = self.root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise StorageBoundaryError("symlinked storage components are not allowed")


class RawEventBatchWriter:
    SCHEMA_VERSION = "douyin-event-jsonl.v1"

    def __init__(self, storage: SecureStorage):
        self.storage = storage

    def write(
        self,
        *,
        session_code: str,
        batch_index: int,
        events: Iterable[dict[str, Any]],
        finalized_at: datetime | None = None,
    ) -> dict[str, Any]:
        if batch_index < 0:
            raise ValueError("batch_index must be non-negative")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", session_code):
            raise ValueError("session_code must be a safe path component")
        rows = [self._normalize_event(event) for event in events]
        finalized = (finalized_at or datetime.now(UTC)).astimezone(UTC)
        relative_path = f"events/{session_code}/events-{batch_index:08d}.jsonl.gz"
        buffer = io.BytesIO()
        with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as compressed:
            for row in rows:
                compressed.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                compressed.write(b"\n")
        content = buffer.getvalue()
        path = self.storage.atomic_write(relative_path, content, mode=0o600)
        received_times = [self._parse_time(row["received_at"]) for row in rows]
        server_times = [
            parsed
            for row in rows
            if row.get("server_at")
            for parsed in [self._parse_time(row["server_at"])]
        ]
        event_types = Counter(str(row.get("event_type") or "unknown") for row in rows)
        fallback = finalized.isoformat().replace("+00:00", "Z")
        return {
            "batch_index": batch_index,
            "relative_path": relative_path,
            "schema_version": self.SCHEMA_VERSION,
            "content_encoding": "gzip",
            "file_mode": 0o600,
            "file_size": path.stat().st_size,
            "checksum_sha256": hashlib.sha256(content).hexdigest(),
            "event_count": len(rows),
            "event_types": dict(sorted(event_types.items())),
            "first_server_at": min(server_times).isoformat().replace("+00:00", "Z")
            if server_times
            else None,
            "last_server_at": max(server_times).isoformat().replace("+00:00", "Z")
            if server_times
            else None,
            "first_received_at": min(received_times).isoformat().replace("+00:00", "Z")
            if received_times
            else fallback,
            "last_received_at": max(received_times).isoformat().replace("+00:00", "Z")
            if received_times
            else fallback,
            "finalized_at": fallback,
        }

    @staticmethod
    def _normalize_event(event: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(event, dict):
            raise TypeError("raw event must be a JSON object")
        normalized = dict(event)
        received_at = normalized.get("received_at") or datetime.now(UTC).isoformat()
        parsed_received = RawEventBatchWriter._parse_time(str(received_at))
        normalized["received_at"] = parsed_received.isoformat().replace("+00:00", "Z")
        server_at = normalized.get("server_at")
        if server_at:
            normalized["server_at"] = RawEventBatchWriter._parse_time(str(server_at)).isoformat().replace(
                "+00:00", "Z"
            )
        normalized["event_type"] = str(normalized.get("event_type") or "unknown")
        return normalized

    @staticmethod
    def _parse_time(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("event timestamps must include an offset")
        return parsed.astimezone(UTC)


def initialize_private_config(example: Path, destination: Path) -> None:
    if destination.exists():
        SecureStorage.require_private_config(destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    content = example.read_bytes()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    restrict_private_permissions(destination, 0o600)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
