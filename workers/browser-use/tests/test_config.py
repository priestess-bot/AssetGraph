from __future__ import annotations

import pytest

from browser_use_worker.config import WorkerConfig


def test_worker_config_reads_lease_heartbeat_interval(monkeypatch) -> None:
    monkeypatch.setenv("BROWSER_USE_LEASE_HEARTBEAT_INTERVAL_SECONDS", "12.5")

    config = WorkerConfig.from_env()

    assert config.lease_heartbeat_interval_seconds == 12.5


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf"])
def test_worker_config_rejects_non_positive_or_non_finite_heartbeat_interval(monkeypatch, value: str) -> None:
    monkeypatch.setenv("BROWSER_USE_LEASE_HEARTBEAT_INTERVAL_SECONDS", value)

    with pytest.raises(ValueError, match="heartbeat interval"):
        WorkerConfig.from_env()
