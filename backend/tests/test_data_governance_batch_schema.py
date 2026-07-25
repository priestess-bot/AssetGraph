from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.contracts import EventEnvelope
from app.schemas.data_governance import StandardEventBatchIngest, StandardEventBatchRow


def _row(source_event_id: str) -> StandardEventBatchRow:
    now = datetime(2026, 7, 25, tzinfo=UTC)
    return StandardEventBatchRow(
        entity_type="live_session",
        entity_id="OPS-001",
        envelope=EventEnvelope(
            event_id=uuid4(),
            source_system="manual-export",
            source_event_id=source_event_id,
            schema_version="live-metric.v1",
            operation="upsert",
            event_time=now,
            processing_time=now,
            payload={"orders": 2},
        ),
    )


def test_standard_event_batch_requires_unique_source_event_ids() -> None:
    batch = StandardEventBatchIngest(
        contract_code="manual-live-metrics",
        contract_revision=1,
        source_batch_id="export-20260725-01",
        rows=[_row("event-001"), _row("event-002")],
    )
    assert len(batch.rows) == 2

    with pytest.raises(ValidationError, match="at most once"):
        StandardEventBatchIngest(
            contract_code="manual-live-metrics",
            contract_revision=1,
            source_batch_id="export-20260725-01",
            rows=[_row("event-001"), _row("event-001")],
        )
