from __future__ import annotations

from typing import Any
from uuid import uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.contracts import canonical_fingerprint, canonical_json_bytes
from app.domain.errors import DomainConflictError, DomainValidationError
from app.services.redaction import redact_sensitive_fields


MAX_DRAFT_BYTES = 256 * 1024


class ConsoleDraftRepository:
    """Optimistically concurrent storage for mutable, non-authoritative UI drafts."""

    def __init__(self, connection: Connection):
        self.connection = connection

    def get_draft(self, entity_type: str, entity_code: str, draft_kind: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM console_drafts
                WHERE entity_type = %s AND entity_code = %s AND draft_kind = %s
                """,
                (entity_type, entity_code, draft_kind),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    def save_draft(
        self,
        *,
        entity_type: str,
        entity_code: str,
        draft_kind: str,
        schema_version: str,
        expected_revision: int,
        base_entity_revision: int,
        document: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        self._validate_document(document)
        fingerprint = canonical_fingerprint(
            {
                "entity_type": entity_type,
                "entity_code": entity_code,
                "draft_kind": draft_kind,
                "schema_version": schema_version,
                "base_entity_revision": base_entity_revision,
                "document": document,
            }
        )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM console_drafts
                WHERE entity_type = %s AND entity_code = %s AND draft_kind = %s
                FOR UPDATE
                """,
                (entity_type, entity_code, draft_kind),
            )
            current = cursor.fetchone()
            if current is None:
                if expected_revision != 0:
                    self.connection.rollback()
                    self._revision_conflict(expected_revision, 0, None)
                draft_code = f"DRAFT-{uuid4().hex}"
                cursor.execute(
                    """
                    INSERT INTO console_drafts (
                        draft_code, entity_type, entity_code, draft_kind,
                        schema_version, draft_revision, base_entity_revision,
                        status, document, content_fingerprint, created_by, updated_by
                    )
                    VALUES (%s, %s, %s, %s, %s, 1, %s, 'active', %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        draft_code,
                        entity_type,
                        entity_code,
                        draft_kind,
                        schema_version,
                        base_entity_revision,
                        Jsonb(document),
                        fingerprint,
                        actor_id,
                        actor_id,
                    ),
                )
                saved = cursor.fetchone()
                event_type = "created"
            else:
                actual_revision = int(current["draft_revision"])
                if current["content_fingerprint"] == fingerprint:
                    self.connection.rollback()
                    return self._serialize(current)
                if actual_revision != expected_revision:
                    self.connection.rollback()
                    self._revision_conflict(expected_revision, actual_revision, current["content_fingerprint"])
                if current["status"] == "active" and int(current["base_entity_revision"]) != base_entity_revision:
                    self.connection.rollback()
                    raise DomainConflictError(
                        "CONSOLE_DRAFT_BASE_REVISION_CONFLICT",
                        "The active draft cannot be silently rebased to another entity revision",
                        details={
                            "draft_revision": actual_revision,
                            "draft_base_revision": int(current["base_entity_revision"]),
                            "requested_base_revision": base_entity_revision,
                        },
                    )
                next_revision = actual_revision + 1
                event_type = "reopened" if current["status"] == "consumed" else "saved"
                cursor.execute(
                    """
                    UPDATE console_drafts
                    SET schema_version = %s, draft_revision = %s,
                        base_entity_revision = %s, status = 'active', document = %s,
                        content_fingerprint = %s, updated_by = %s, updated_at = now()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        schema_version,
                        next_revision,
                        base_entity_revision,
                        Jsonb(document),
                        fingerprint,
                        actor_id,
                        current["id"],
                    ),
                )
                saved = cursor.fetchone()
            self._append_event(cursor, saved, event_type=event_type, actor_id=actor_id)
            self._append_audit(cursor, saved, event_type=event_type, actor_id=actor_id)
        self.connection.commit()
        return self._serialize(saved)

    @staticmethod
    def _validate_document(document: dict[str, Any]) -> None:
        if len(canonical_json_bytes(document)) > MAX_DRAFT_BYTES:
            raise DomainValidationError(
                "CONSOLE_DRAFT_TOO_LARGE",
                f"Console drafts are limited to {MAX_DRAFT_BYTES} canonical bytes",
            )
        redaction = redact_sensitive_fields(document, context="console_draft")
        if redaction.redacted_paths:
            raise DomainValidationError(
                "CONSOLE_DRAFT_SENSITIVE_DATA_REJECTED",
                "Sensitive or personal fields cannot be persisted in a generic Console draft",
                details={"paths": list(redaction.redacted_paths)},
            )

    @staticmethod
    def _revision_conflict(expected: int, actual: int, fingerprint: str | None) -> None:
        raise DomainConflictError(
            "CONSOLE_DRAFT_REVISION_CONFLICT",
            "Console draft changed since it was loaded",
            details={
                "expected_revision": expected,
                "actual_revision": actual,
                "actual_fingerprint": fingerprint,
            },
        )

    @staticmethod
    def _append_event(cursor: Any, draft: dict[str, Any], *, event_type: str, actor_id: str) -> None:
        cursor.execute(
            """
            INSERT INTO console_draft_events (
                draft_id, draft_code, draft_revision, event_type,
                base_entity_revision, content_fingerprint, actor_id, event_metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                draft["id"],
                draft["draft_code"],
                draft["draft_revision"],
                event_type,
                draft["base_entity_revision"],
                draft["content_fingerprint"],
                actor_id,
                Jsonb({"schema_version": draft["schema_version"], "status": draft["status"]}),
            ),
        )

    @staticmethod
    def _append_audit(cursor: Any, draft: dict[str, Any], *, event_type: str, actor_id: str) -> None:
        cursor.execute(
            """
            INSERT INTO audit_events (
                audit_event_id, principal_type, principal_id, action,
                target_type, target_code, target_revision, outcome,
                reason_code, details
            )
            VALUES (%s, 'user', %s, 'save_draft', %s, %s, %s,
                    'succeeded', %s, %s)
            """,
            (
                uuid4(),
                actor_id,
                draft["entity_type"],
                draft["entity_code"],
                draft["base_entity_revision"] or None,
                f"CONSOLE_DRAFT_{event_type.upper()}",
                Jsonb(
                    {
                        "draft_code": draft["draft_code"],
                        "draft_kind": draft["draft_kind"],
                        "draft_revision": draft["draft_revision"],
                        "content_fingerprint": draft["content_fingerprint"],
                    }
                ),
            ),
        )

    @staticmethod
    def _serialize(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["id"] = str(result["id"])
        result["document"] = dict(result["document"])
        return result
