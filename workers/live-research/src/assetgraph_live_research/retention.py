from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from .storage import SecureStorage


class RetentionAPI(Protocol):
    def claim_retention(
        self, worker_id: str, lease_seconds: int, limit: int = 100
    ) -> list[dict[str, Any]]: ...

    def complete_retention(self, payload: dict[str, Any]) -> None: ...


@dataclass(slots=True)
class RetentionWorker:
    api: RetentionAPI
    storage: SecureStorage
    worker_id: str
    lease_seconds: int = 300
    batch_limit: int = 100

    def run_once(self) -> int:
        candidates = self.api.claim_retention(
            self.worker_id,
            self.lease_seconds,
            self.batch_limit,
        )
        completed = 0
        for candidate in candidates:
            if candidate.get("entity_type") != "capture_chunk":
                raise RuntimeError("retention API returned a non-video entity")
            deleted = self.storage.delete_private_file(
                candidate["relative_path"],
                expected_checksum_sha256=candidate.get("checksum_sha256"),
            )
            self.api.complete_retention(
                {
                    "entity_type": candidate["entity_type"],
                    "entity_id": candidate["entity_id"],
                    "worker_id": self.worker_id,
                    "claim_token": candidate["claim_token"],
                    "deletion_attempt_id": str(uuid4()),
                    "deletion_reason": "retention_30_days",
                    "details": {"file_was_present": deleted},
                }
            )
            completed += 1
        return completed
