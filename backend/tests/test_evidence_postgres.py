from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from app.repositories.evidence import EvidenceRepository
from app.services.manifests import seal_run_manifest, verify_sealed_manifest


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def _manifest(seed: int) -> dict:
    return {
        "input_revisions": [{"object_type": "content_project", "code": "CONTENT-1", "revision": 1}],
        "input_artifacts": [],
        "inventory_refs": [],
        "material_refs": [],
        "constraint_refs": [],
        "rights_refs": [],
        "template_refs": [],
        "fact_refs": [],
        "content_refs": [],
        "model_strategies": [],
        "prompt_revisions": [],
        "code_revision": "d946631",
        "tool_versions": [{"name": "assetgraph", "version": "test"}],
        "random_seed": seed,
        "environment": {"profile": "isolated-postgres"},
    }


def test_artifact_deduplication_links_and_append_only_guards() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository = EvidenceRepository(connection)
        first = repository.register_artifact(
            artifact_kind="test_evidence",
            media_type="application/json",
            schema_version="artifact.v1",
            storage_uri=f"s3://evidence/{suffix}/one",
            checksum_sha256=suffix.ljust(64, "0"),
            byte_size=10,
            producer_type="test",
            producer_code=suffix,
            producer_revision=1,
            sensitivity="internal",
            retention_policy_code="test",
            encryption_key_ref=None,
            metadata={"case": suffix},
        )
        replay = repository.register_artifact(
            artifact_kind="ignored_on_dedupe",
            media_type="application/json",
            schema_version="artifact.v1",
            storage_uri=f"s3://evidence/{suffix}/two",
            checksum_sha256=suffix.ljust(64, "0"),
            byte_size=10,
            producer_type="test",
            producer_code=suffix,
            producer_revision=1,
            sensitivity="internal",
            retention_policy_code="test",
            encryption_key_ref=None,
            metadata={},
        )
        assert replay["artifact_code"] == first["artifact_code"]

        second_checksum = ("f" + suffix[1:]).ljust(64, "1")
        second = repository.register_artifact(
            artifact_kind="test_evidence",
            media_type="application/json",
            schema_version="artifact.v1",
            storage_uri=f"s3://evidence/{suffix}/derived",
            checksum_sha256=second_checksum,
            byte_size=11,
            producer_type="test",
            producer_code=suffix,
            producer_revision=2,
            sensitivity="internal",
            retention_policy_code="test",
            encryption_key_ref=None,
            metadata={},
        )
        repository.link_artifact_input(second["artifact_code"], first["artifact_code"], relation_type="derived_from")
        repository.link_artifact_input(second["artifact_code"], first["artifact_code"], relation_type="derived_from")

        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE artifact_refs SET metadata = '{}' WHERE artifact_code = %s",
                    (first["artifact_code"],),
                )
        connection.rollback()


def test_manifest_chain_lineage_and_append_only_guards() -> None:
    suffix = uuid4().hex
    signing_key = b"integration-test-signing-key"
    with psycopg.connect(DATABASE_URL) as connection:
        repository = EvidenceRepository(connection)
        first_sealed = seal_run_manifest(_manifest(1), signing_key=signing_key, key_id="test-key")
        first = repository.persist_run_manifest(run_code=f"RUN-{suffix}-1", sealed=first_sealed)
        replay = repository.persist_run_manifest(run_code=f"RUN-{suffix}-ignored", sealed=first_sealed)
        second_sealed = seal_run_manifest(_manifest(2), signing_key=signing_key, key_id="test-key")
        second = repository.persist_run_manifest(run_code=f"RUN-{suffix}-2", sealed=second_sealed)

        assert replay["manifest_code"] == first["manifest_code"]
        assert verify_sealed_manifest(first_sealed, signing_key=signing_key)
        assert second["previous_chain_hash"] == first["chain_hash"]
        assert second["chain_hash"] != first["chain_hash"]

        edge = {
            "run_code": f"RUN-{suffix}-2",
            "source_namespace": "assetgraph.content",
            "source_name": f"script-{suffix}",
            "source_version": "1",
            "target_namespace": "assetgraph.production",
            "target_name": f"build-plan-{suffix}",
            "target_version": "1",
            "relation_type": "derived_from",
            "facets": {"manifest": second["manifest_code"]},
        }
        stored_edge = repository.append_lineage_edge(edge)
        replay_edge = repository.append_lineage_edge(edge)
        assert replay_edge["id"] == stored_edge["id"]

        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM lineage_edges WHERE id = %s",
                    (stored_edge["id"],),
                )
        connection.rollback()


def test_outbox_replay_dead_letter_and_projection_watermark_are_deterministic() -> None:
    event_id = uuid4()
    now = datetime.now(UTC)
    projection_name = f"test-projection-{uuid4().hex}"
    with psycopg.connect(DATABASE_URL) as connection:
        repository = EvidenceRepository(connection)
        first_id = repository.enqueue_outbox(
            aggregate_type="content_project",
            aggregate_code="CONTENT-1",
            aggregate_revision=1,
            event_type="content.updated",
            schema_version="content-event.v1",
            payload={"revision": 1},
            occurred_at=now,
            trace_id="a" * 32,
            event_id=event_id,
        )
        replay_id = repository.enqueue_outbox(
            aggregate_type="content_project",
            aggregate_code="CONTENT-1",
            aggregate_revision=1,
            event_type="content.updated",
            schema_version="content-event.v1",
            payload={"revision": 1},
            occurred_at=now,
            trace_id="a" * 32,
            event_id=event_id,
        )
        connection.commit()
        assert first_id == replay_id == event_id

        claimed = repository.claim_outbox_batch(limit=10, max_attempts=3)
        current = next(row for row in claimed if row["event_id"] == str(event_id))
        assert current["publish_attempts"] == 1
        assert repository.record_outbox_failure(str(event_id), error_code="BROKER_DOWN", retry_after=timedelta(0))
        claimed_again = repository.claim_outbox_batch(limit=10, max_attempts=3)
        current_again = next(row for row in claimed_again if row["event_id"] == str(event_id))
        assert current_again["publish_attempts"] == 2
        assert repository.mark_outbox_published(str(event_id))
        assert all(row["event_id"] != str(event_id) for row in repository.claim_outbox_batch(limit=100))

        latest = repository.advance_projection_checkpoint(
            projection_name=projection_name,
            projection_version="projection.v1",
            event_id=str(event_id),
            watermark_occurred_at=now,
            lag_seconds=0,
        )
        stale = repository.advance_projection_checkpoint(
            projection_name=projection_name,
            projection_version="projection.v0",
            event_id=str(uuid4()),
            watermark_occurred_at=now - timedelta(days=1),
            lag_seconds=100,
        )
        assert stale["last_event_id"] == latest["last_event_id"]
        assert stale["projection_version"] == "projection.v1"
        assert stale["status"] == "current"
