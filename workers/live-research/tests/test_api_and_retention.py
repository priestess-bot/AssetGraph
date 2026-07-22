from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from assetgraph_live_research.api_client import LiveResearchAPIClient, LiveResearchAPIError
from assetgraph_live_research.retention import RetentionWorker
from assetgraph_live_research.storage import SecureStorage


def test_worker_client_sends_bearer_and_bound_worker_identity() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"target_code": "target_1"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = LiveResearchAPIClient(
        worker_token="secret",
        worker_id="worker-1",
        client=http,
    )
    client.claim_watch_target("worker-1", 120)

    request = captured[0]
    assert request.headers["Authorization"] == "Bearer secret"
    assert request.headers["X-AssetGraph-Worker-ID"] == "worker-1"
    assert json.loads(request.content)["worker_id"] == "worker-1"
    with pytest.raises(LiveResearchAPIError, match="does not match"):
        client.claim_watch_target("worker-2", 120)
    client.close()


class _RetentionAPI:
    def __init__(self, candidates: list[dict[str, Any]]):
        self.candidates = candidates
        self.completed: list[dict[str, Any]] = []

    def claim_retention(
        self, worker_id: str, lease_seconds: int, limit: int = 100
    ) -> list[dict[str, Any]]:
        assert worker_id == "retention-worker"
        assert lease_seconds == 300
        assert limit == 100
        return self.candidates

    def complete_retention(self, payload: dict[str, Any]) -> None:
        self.completed.append(payload)


def test_retention_deletes_only_capture_chunks(tmp_path: Path) -> None:
    storage = SecureStorage(tmp_path / "root")
    storage.atomic_write("raw-recordings/s/chunks/chunk.ts", b"video")
    api = _RetentionAPI(
        [
            {
                "entity_type": "capture_chunk",
                "entity_id": "chunk-id",
                "relative_path": "raw-recordings/s/chunks/chunk.ts",
                "claim_token": "11111111-1111-1111-1111-111111111111",
            }
        ]
    )

    assert RetentionWorker(api, storage, "retention-worker").run_once() == 1
    assert not storage.resolve("raw-recordings/s/chunks/chunk.ts").exists()
    assert api.completed[0]["deletion_reason"] == "retention_30_days"
    assert api.completed[0]["worker_id"] == "retention-worker"


def test_retention_refuses_permanent_raw_events(tmp_path: Path) -> None:
    storage = SecureStorage(tmp_path / "root")
    path = storage.atomic_write("events/s/events-00000000.jsonl.gz", b"event")
    api = _RetentionAPI(
        [
            {
                "entity_type": "raw_event_batch",
                "entity_id": "batch-id",
                "relative_path": "events/s/events-00000000.jsonl.gz",
                "claim_token": "11111111-1111-1111-1111-111111111111",
            }
        ]
    )

    with pytest.raises(RuntimeError, match="non-video"):
        RetentionWorker(api, storage, "retention-worker").run_once()
    assert path.exists()
    assert api.completed == []
