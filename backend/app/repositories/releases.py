from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.errors import DomainConflictError, DomainValidationError
from app.domain.state_machines import DELIVERY_STATE_MACHINE, RELEASE_STATE_MACHINE
from app.services.state_transitions import require_audited_transition


class ReleaseRepository:
    def __init__(self, connection: Connection):
        self.connection = connection

    def create_release_with_manifest(
        self,
        *,
        subject_type: str,
        subject_code: str,
        subject_revision: int,
        carrier_kind: str,
        created_by: str,
        manifest: dict[str, Any],
        manifest_fingerprint: str,
        signature_algorithm: str,
        signature_key_id: str,
        signature_value: str,
        commit: bool = True,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT release.* FROM release_manifests AS manifest
                JOIN releases AS release ON release.id = manifest.release_id
                WHERE manifest.manifest_fingerprint = %s
                """,
                (manifest_fingerprint,),
            )
            existing = cursor.fetchone()
            if existing is not None:
                if commit:
                    self.connection.rollback()
                return self.get_release(existing["release_code"])
            release_code = self._next_code(cursor, prefix="RELEASE", object_type="release")
            cursor.execute(
                """
                INSERT INTO releases (
                    release_code, subject_type, subject_code, subject_revision,
                    carrier_kind, status, current_manifest_revision,
                    release_fingerprint, created_by
                )
                VALUES (%s, %s, %s, %s, %s, 'candidate', 1, %s, %s)
                RETURNING id
                """,
                (
                    release_code,
                    subject_type,
                    subject_code,
                    subject_revision,
                    carrier_kind,
                    manifest_fingerprint,
                    created_by,
                ),
            )
            release_id = cursor.fetchone()["id"]
            manifest_code = f"{release_code}-M001"
            cursor.execute(
                """
                INSERT INTO release_manifests (
                    manifest_code, release_id, release_code, revision_number,
                    schema_version, carrier_kind, subject_refs, artifact_refs,
                    rights_snapshot, quality_snapshot, lineage_snapshot,
                    carrier_facet, manifest_fingerprint, signature_algorithm,
                    signature_key_id, signature_value
                )
                VALUES (%s, %s, %s, 1, 'release-manifest.v1', %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    manifest_code,
                    release_id,
                    release_code,
                    carrier_kind,
                    Jsonb(manifest["subject_refs"]),
                    Jsonb(manifest["artifact_refs"]),
                    Jsonb(manifest["rights_snapshot"]),
                    Jsonb(manifest["quality_snapshot"]),
                    Jsonb(manifest["lineage_snapshot"]),
                    Jsonb(manifest["carrier_facet"]),
                    manifest_fingerprint,
                    signature_algorithm,
                    signature_key_id,
                    signature_value,
                ),
            )
            self._append_history(
                cursor,
                release_id=release_id,
                from_status=None,
                to_status="candidate",
                actor_id=created_by,
                reason_code="RELEASE_CREATED",
                evidence={"manifest_code": manifest_code, "fingerprint": manifest_fingerprint},
            )
        if commit:
            self.connection.commit()
        return self.get_release(release_code)

    def get_release(self, release_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM releases WHERE release_code = %s", (release_code,))
            release = cursor.fetchone()
            if release is None:
                return None
            cursor.execute(
                """
                SELECT * FROM release_manifests
                WHERE release_id = %s AND revision_number = %s
                """,
                (release["id"], release["current_manifest_revision"]),
            )
            manifest = cursor.fetchone()
            cursor.execute(
                "SELECT * FROM release_approvals WHERE release_id = %s ORDER BY decided_at, id",
                (release["id"],),
            )
            approvals = cursor.fetchall()
            cursor.execute(
                "SELECT * FROM delivery_attempts WHERE release_id = %s ORDER BY created_at, id",
                (release["id"],),
            )
            deliveries = cursor.fetchall()
        result = self._serialize(release)
        result["manifest"] = self._serialize(manifest)
        result["approvals"] = [self._serialize(row) for row in approvals]
        result["deliveries"] = [self._serialize(row) for row in deliveries]
        return result

    def list_releases(self, project_code: str | None = None) -> list[dict[str, Any]]:
        project_filter = ""
        parameters: tuple[str, ...] = ()
        if project_code is not None:
            project_filter = """
                   WHERE EXISTS (
                       SELECT 1
                       FROM (
                           SELECT live.release_code
                           FROM functional_live_room_plans AS live
                           WHERE live.project_code = %s
                           UNION ALL
                           SELECT video.release_code
                           FROM functional_video_plans AS video
                           WHERE video.project_code = %s
                       ) AS project_release
                       WHERE project_release.release_code = release.release_code
                   )"""
            parameters = (project_code, project_code)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""SELECT release.release_code, release.subject_type, release.subject_code,
                          release.subject_revision, release.carrier_kind, release.status,
                          release.current_manifest_revision, release.release_fingerprint,
                          release.created_at, release.updated_at,
                          manifest.manifest_code, manifest.manifest_fingerprint,
                          COUNT(delivery.id) AS delivery_count
                   FROM releases release
                   JOIN release_manifests manifest
                     ON manifest.release_id = release.id AND manifest.revision_number = release.current_manifest_revision
                   LEFT JOIN delivery_attempts delivery ON delivery.release_id = release.id
                   {project_filter}
                   GROUP BY release.id, manifest.id
                   ORDER BY release.updated_at DESC, release.release_code""",
                parameters,
            )
            rows = cursor.fetchall()
        return [self._serialize(row) for row in rows]

    def verify_artifact_refs(self, artifact_refs: list[dict[str, Any]]) -> list[str]:
        failures: list[str] = []
        with self.connection.cursor(row_factory=dict_row) as cursor:
            for reference in artifact_refs:
                code = reference.get("artifact_code")
                checksum = reference.get("checksum_sha256")
                if not code or not checksum:
                    failures.append("ARTIFACT_REFERENCE_INCOMPLETE")
                    continue
                cursor.execute(
                    "SELECT checksum_sha256 FROM artifact_refs WHERE artifact_code = %s",
                    (code,),
                )
                row = cursor.fetchone()
                if row is None:
                    failures.append(f"ARTIFACT_NOT_FOUND:{code}")
                elif row["checksum_sha256"] != checksum:
                    failures.append(f"ARTIFACT_CHECKSUM_MISMATCH:{code}")
        return failures

    def transition_release(
        self,
        release_code: str,
        *,
        expected_status: str,
        target_status: str,
        actor_id: str,
        reason_code: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        require_audited_transition(
            self.connection,
            RELEASE_STATE_MACHINE,
            current=expected_status,
            target=target_status,
            principal_type="user",
            principal_id=actor_id,
            target_type="release",
            target_code=release_code,
        )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM releases WHERE release_code = %s FOR UPDATE", (release_code,))
            current = cursor.fetchone()
            if current is None:
                self.connection.rollback()
                raise KeyError(release_code)
            if current["status"] != expected_status:
                self.connection.rollback()
                raise DomainConflictError(
                    "RELEASE_STATUS_CONFLICT",
                    "Release status changed since it was loaded",
                    details={"expected_status": expected_status, "actual_status": current["status"]},
                )
            cursor.execute(
                """
                UPDATE releases
                SET status = %s, updated_at = now(),
                    revoked_at = CASE WHEN %s = 'revoked' THEN now() ELSE revoked_at END
                WHERE id = %s
                RETURNING *
                """,
                (target_status, target_status, current["id"]),
            )
            row = cursor.fetchone()
            self._append_history(
                cursor,
                release_id=current["id"],
                from_status=expected_status,
                to_status=target_status,
                actor_id=actor_id,
                reason_code=reason_code,
                evidence=evidence,
            )
        self.connection.commit()
        return self._serialize(row)

    def add_approval(
        self,
        release_code: str,
        *,
        decision: str,
        structured_reason: dict[str, Any],
        approved_scope: dict[str, Any],
        decided_by: str,
        expected_manifest_revision: int | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM releases WHERE release_code = %s FOR UPDATE", (release_code,))
            release = cursor.fetchone()
            if release is None:
                self.connection.rollback()
                raise KeyError(release_code)
            if release["status"] != "awaiting_approval":
                self.connection.rollback()
                raise DomainConflictError("RELEASE_NOT_AWAITING_APPROVAL", "Release is not awaiting approval")
            if (
                expected_manifest_revision is not None
                and int(release["current_manifest_revision"]) != expected_manifest_revision
            ):
                self.connection.rollback()
                raise DomainConflictError(
                    "RELEASE_MANIFEST_REVISION_CONFLICT",
                    "Release manifest changed since the approval was prepared",
                    details={
                        "expected_revision": expected_manifest_revision,
                        "actual_revision": int(release["current_manifest_revision"]),
                    },
                )
            if release["created_by"] == decided_by:
                self.connection.rollback()
                raise DomainValidationError(
                    "RELEASE_SELF_APPROVAL_FORBIDDEN",
                    "Release creator cannot approve their own release",
                )
            cursor.execute(
                """
                SELECT * FROM release_manifests
                WHERE release_id = %s AND revision_number = %s
                """,
                (release["id"], release["current_manifest_revision"]),
            )
            manifest = cursor.fetchone()
            approval_code = self._next_code(cursor, prefix="APPROVAL", object_type="release_approval")
            cursor.execute(
                """
                INSERT INTO release_approvals (
                    approval_code, release_id, manifest_id, decision,
                    structured_reason, approved_scope, decided_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    approval_code,
                    release["id"],
                    manifest["id"],
                    decision,
                    Jsonb(structured_reason),
                    Jsonb(approved_scope),
                    decided_by,
                ),
            )
            approval = cursor.fetchone()
            target_status = "approved" if decision == "approve" else "candidate"
            cursor.execute(
                "UPDATE releases SET status = %s, updated_at = now() WHERE id = %s",
                (target_status, release["id"]),
            )
            self._append_history(
                cursor,
                release_id=release["id"],
                from_status="awaiting_approval",
                to_status=target_status,
                actor_id=decided_by,
                reason_code=f"RELEASE_{decision.upper()}",
                evidence={"approval_code": approval_code, "manifest_code": manifest["manifest_code"]},
            )
        if commit:
            self.connection.commit()
        return self._serialize(approval)

    def create_delivery_attempt(
        self,
        release_code: str,
        *,
        target_type: str,
        target_id: str,
        adapter_type: str,
        idempotency_key: str,
        authorization_id: str | None,
        request_summary: dict[str, Any],
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM releases WHERE release_code = %s FOR UPDATE", (release_code,))
            release = cursor.fetchone()
            if release is None:
                self.connection.rollback()
                raise KeyError(release_code)
            if release["status"] not in {"approved", "delivery_pending", "delivery_failed"}:
                self.connection.rollback()
                raise DomainConflictError("RELEASE_NOT_DELIVERABLE", "Release has not been approved for delivery")
            cursor.execute(
                """
                SELECT * FROM delivery_attempts
                WHERE target_type = %s AND target_id = %s AND idempotency_key = %s
                """,
                (target_type, target_id, idempotency_key),
            )
            existing = cursor.fetchone()
            if existing is not None:
                self.connection.rollback()
                return self._serialize(existing)
            cursor.execute(
                """
                SELECT id FROM release_manifests
                WHERE release_id = %s AND revision_number = %s
                """,
                (release["id"], release["current_manifest_revision"]),
            )
            manifest_id = cursor.fetchone()["id"]
            delivery_code = self._next_code(cursor, prefix="DELIVERY", object_type="delivery_attempt")
            cursor.execute(
                """
                INSERT INTO delivery_attempts (
                    delivery_code, release_id, manifest_id, target_type,
                    target_id, adapter_type, idempotency_key, authorization_id,
                    status, request_summary
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'prepared', %s)
                RETURNING *
                """,
                (
                    delivery_code,
                    release["id"],
                    manifest_id,
                    target_type,
                    target_id,
                    adapter_type,
                    idempotency_key,
                    authorization_id,
                    Jsonb(request_summary),
                ),
            )
            delivery = cursor.fetchone()
            if release["status"] != "delivery_pending":
                cursor.execute(
                    "UPDATE releases SET status = 'delivery_pending', updated_at = now() WHERE id = %s",
                    (release["id"],),
                )
                self._append_history(
                    cursor,
                    release_id=release["id"],
                    from_status=release["status"],
                    to_status="delivery_pending",
                    actor_id=None,
                    reason_code="DELIVERY_PREPARED",
                    evidence={"delivery_code": delivery_code},
                )
        self.connection.commit()
        return self._serialize(delivery)

    def transition_delivery(
        self,
        delivery_code: str,
        *,
        expected_status: str,
        target_status: str,
        response_summary: dict[str, Any] | None = None,
        readback_evidence: dict[str, Any] | None = None,
        external_identity: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        require_audited_transition(
            self.connection,
            DELIVERY_STATE_MACHINE,
            current=expected_status,
            target=target_status,
            principal_type="system",
            principal_id=None,
            target_type="delivery_attempt",
            target_code=delivery_code,
        )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM delivery_attempts WHERE delivery_code = %s FOR UPDATE",
                (delivery_code,),
            )
            current = cursor.fetchone()
            if current is None:
                self.connection.rollback()
                raise KeyError(delivery_code)
            if current["status"] != expected_status:
                self.connection.rollback()
                raise DomainConflictError(
                    "DELIVERY_STATUS_CONFLICT",
                    "Delivery status changed since it was loaded",
                )
            if target_status == "succeeded" and (not external_identity or not readback_evidence):
                self.connection.rollback()
                raise DomainValidationError(
                    "DELIVERY_READBACK_REQUIRED",
                    "Successful delivery requires external identity and read-back evidence",
                )
            release = None
            release_status = None
            if target_status in {"succeeded", "failed", "reconcile_required"}:
                cursor.execute(
                    "SELECT * FROM releases WHERE id = %s FOR UPDATE",
                    (current["release_id"],),
                )
                release = cursor.fetchone()
                if release is None:
                    self.connection.rollback()
                    raise DomainConflictError(
                        "DELIVERY_RELEASE_NOT_FOUND",
                        "Delivery attempt no longer has an associated release",
                    )
                release_status = {
                    "succeeded": "delivered",
                    "failed": "delivery_failed",
                    "reconcile_required": "reconcile_required",
                }[target_status]
                try:
                    RELEASE_STATE_MACHINE.require_transition(release["status"], release_status)
                except DomainConflictError as exc:
                    self.connection.rollback()
                    raise DomainConflictError(
                        "DELIVERY_RELEASE_STATUS_CONFLICT",
                        "Delivery callback cannot change the current release state",
                        details={
                            "delivery_code": delivery_code,
                            "release_code": release["release_code"],
                            "release_status": release["status"],
                            "requested_release_status": release_status,
                            "allowed": exc.details.get("allowed", []),
                        },
                    ) from exc
            cursor.execute(
                """
                UPDATE delivery_attempts
                SET status = %s,
                    response_summary = COALESCE(%s, response_summary),
                    readback_evidence = COALESCE(%s, readback_evidence),
                    external_identity = COALESCE(%s, external_identity),
                    error_code = %s,
                    started_at = CASE WHEN %s = 'committing' THEN COALESCE(started_at, now()) ELSE started_at END,
                    completed_at = CASE WHEN %s IN ('succeeded', 'failed', 'cancelled') THEN now() ELSE completed_at END
                WHERE id = %s
                RETURNING *
                """,
                (
                    target_status,
                    Jsonb(response_summary) if response_summary is not None else None,
                    Jsonb(readback_evidence) if readback_evidence is not None else None,
                    Jsonb(external_identity) if external_identity is not None else None,
                    error_code,
                    target_status,
                    target_status,
                    current["id"],
                ),
            )
            row = cursor.fetchone()
            if release is not None and release_status is not None:
                cursor.execute(
                    "UPDATE releases SET status = %s, updated_at = now() WHERE id = %s",
                    (release_status, release["id"]),
                )
                self._append_history(
                    cursor,
                    release_id=release["id"],
                    from_status=release["status"],
                    to_status=release_status,
                    actor_id=None,
                    reason_code=f"DELIVERY_{target_status.upper()}",
                    evidence={"delivery_code": delivery_code},
                )
        self.connection.commit()
        return self._serialize(row)

    def append_exposure(
        self,
        *,
        release_code: str,
        source_system: str,
        source_event_id: str,
        live_session_code: str,
        external_session_id: str | None,
        exposed_content_type: str,
        exposed_content_code: str,
        exposed_content_revision: int,
        start_ms: int,
        end_ms: int,
        event_time: datetime,
        time_mapping_revision: str | None,
        source_evidence: dict[str, Any],
        confidence: float,
        exposure_event_id: UUID | None = None,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT manifest.id FROM releases AS release
                JOIN release_manifests AS manifest
                  ON manifest.release_id = release.id
                 AND manifest.revision_number = release.current_manifest_revision
                WHERE release.release_code = %s AND release.status = 'delivered'
                """,
                (release_code,),
            )
            manifest = cursor.fetchone()
            if manifest is None:
                self.connection.rollback()
                raise DomainConflictError(
                    "EXPOSURE_RELEASE_NOT_DELIVERED",
                    "Exposure must reference a delivered release manifest",
                )
            cursor.execute(
                """
                INSERT INTO content_exposure_events (
                    exposure_event_id, source_system, source_event_id,
                    release_manifest_id, live_session_code, external_session_id,
                    exposed_content_type, exposed_content_code,
                    exposed_content_revision, start_ms, end_ms, event_time,
                    time_mapping_revision, source_evidence, confidence
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_system, source_event_id) DO NOTHING
                RETURNING *
                """,
                (
                    exposure_event_id or uuid4(),
                    source_system,
                    source_event_id,
                    manifest["id"],
                    live_session_code,
                    external_session_id,
                    exposed_content_type,
                    exposed_content_code,
                    exposed_content_revision,
                    start_ms,
                    end_ms,
                    event_time,
                    time_mapping_revision,
                    Jsonb(source_evidence),
                    confidence,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    """
                    SELECT * FROM content_exposure_events
                    WHERE source_system = %s AND source_event_id = %s
                    """,
                    (source_system, source_event_id),
                )
                row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row)

    @staticmethod
    def _append_history(
        cursor: Any,
        *,
        release_id: UUID,
        from_status: str | None,
        to_status: str,
        actor_id: str | None,
        reason_code: str,
        evidence: dict[str, Any],
    ) -> None:
        cursor.execute(
            """
            INSERT INTO release_status_history (
                release_id, from_status, to_status, actor_id, reason_code, evidence
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (release_id, from_status, to_status, actor_id, reason_code, Jsonb(evidence)),
        )

    @staticmethod
    def _serialize(row: dict[str, Any] | None) -> dict[str, Any]:
        if row is None:
            return {}
        result = dict(row)
        for key, value in list(result.items()):
            if isinstance(value, UUID):
                result[key] = str(value)
        return result

    @staticmethod
    def _next_code(cursor: Any, *, prefix: str, object_type: str) -> str:
        sequence_date = datetime.now(UTC).date()
        cursor.execute(
            """
            INSERT INTO domain_sequences (sequence_date, object_type, current_value)
            VALUES (%s, %s, 1)
            ON CONFLICT (sequence_date, object_type)
            DO UPDATE SET current_value = domain_sequences.current_value + 1, updated_at = now()
            RETURNING current_value
            """,
            (sequence_date, object_type),
        )
        value = int(cursor.fetchone()["current_value"])
        return f"{prefix}-{sequence_date:%Y%m%d}-{value:06d}"
