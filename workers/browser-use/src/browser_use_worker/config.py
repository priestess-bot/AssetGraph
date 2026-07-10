from __future__ import annotations

import math
import os
import socket
from dataclasses import dataclass


@dataclass(slots=True)
class WorkerConfig:
    api_base_url: str
    worker_id: str
    lock_ttl_seconds: int = 900
    lease_heartbeat_interval_seconds: float = 30.0
    poll_interval_seconds: float = 5.0
    max_attempts: int = 3
    failure_type: str | None = None
    maitu_project_code: str | None = None
    scene_name: str | None = None
    dry_run: bool = False

    def __post_init__(self) -> None:
        if not math.isfinite(self.lease_heartbeat_interval_seconds) or self.lease_heartbeat_interval_seconds <= 0:
            raise ValueError("lease heartbeat interval must be a positive finite number")

    @classmethod
    def from_env(cls, *, dry_run: bool = False) -> "WorkerConfig":
        default_worker_id = f"browser-use-{socket.gethostname()}-{os.getpid()}"
        return cls(
            api_base_url=os.getenv("ASSETGRAPH_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
            worker_id=os.getenv("BROWSER_USE_WORKER_ID", default_worker_id),
            lock_ttl_seconds=int(os.getenv("BROWSER_USE_LOCK_TTL_SECONDS", "900")),
            lease_heartbeat_interval_seconds=float(os.getenv("BROWSER_USE_LEASE_HEARTBEAT_INTERVAL_SECONDS", "30")),
            poll_interval_seconds=float(os.getenv("BROWSER_USE_POLL_INTERVAL_SECONDS", "5")),
            max_attempts=int(os.getenv("BROWSER_USE_MAX_ATTEMPTS", "3")),
            failure_type=os.getenv("BROWSER_USE_FAILURE_TYPE") or None,
            maitu_project_code=os.getenv("BROWSER_USE_MAITU_PROJECT_CODE") or None,
            scene_name=os.getenv("BROWSER_USE_SCENE_NAME") or None,
            dry_run=dry_run,
        )
