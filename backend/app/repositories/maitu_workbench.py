from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class MaituWorkbenchConflictError(RuntimeError):
    """A workbench command conflicts with the current durable state."""


class MaituWorkbenchLeaseConflictError(MaituWorkbenchConflictError):
    """A worker command does not own a live lease."""


class MaituWorkbenchRepository:
    def __init__(self, connection: Connection):
        self.connection = connection

    def get_protected_resource(self, resource_type: str, resource_id: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM protected_resources
                WHERE resource_type = %s AND resource_id = %s
                  AND revoked_at IS NULL AND effective_at <= now()
                  AND (expires_at IS NULL OR expires_at > now())
                """,
                (resource_type, resource_id),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    # Product fact cards -------------------------------------------------

    def create_product_fact_card(
        self,
        payload: dict[str, Any],
        *,
        content_sha256: str,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            fact_card_code = self._next_code(cursor, "MT-FACT", "MAITU_WB_FACT")
            product_id = self._find_product_id(cursor, payload.get("product_code"))
            approved = bool(payload.get("approve"))
            cursor.execute(
                """
                INSERT INTO maitu_workbench_product_fact_cards (
                    fact_card_code, product_id, product_code, title,
                    current_approved_version
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    fact_card_code,
                    product_id,
                    payload.get("product_code"),
                    payload["title"],
                    1 if approved else None,
                ),
            )
            fact_card_id = cursor.fetchone()["id"]
            version_code = f"{fact_card_code}-V001"
            cursor.execute(
                """
                INSERT INTO maitu_workbench_product_fact_card_versions (
                    fact_card_id, fact_card_code, version_code, version_number,
                    status, content, content_sha256, change_reason, created_by,
                    approved_by, approved_at
                )
                VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    fact_card_id,
                    fact_card_code,
                    version_code,
                    "approved" if approved else "draft",
                    Jsonb(payload["content"]),
                    content_sha256,
                    payload.get("change_reason"),
                    payload.get("created_by"),
                    payload.get("approved_by") if approved else None,
                    datetime.now(UTC) if approved else None,
                ),
            )
        self.connection.commit()
        return self.get_product_fact_card(fact_card_code) or {}

    def list_product_fact_cards(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT fact_card_code
                FROM maitu_workbench_product_fact_cards
                ORDER BY created_at DESC, fact_card_code DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            codes = [row["fact_card_code"] for row in cursor.fetchall()]
        return [row for code in codes if (row := self.get_product_fact_card(code)) is not None]

    def get_product_fact_card(self, fact_card_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM maitu_workbench_product_fact_cards
                WHERE fact_card_code = %s
                """,
                (fact_card_code,),
            )
            card = cursor.fetchone()
            if card is None:
                return None
            cursor.execute(
                """
                SELECT *
                FROM maitu_workbench_product_fact_card_versions
                WHERE fact_card_id = %s
                ORDER BY version_number DESC
                """,
                (card["id"],),
            )
            versions = cursor.fetchall()
        result = self._serialize(card)
        result["versions"] = [self._serialize(row) for row in versions]
        return result

    def create_product_fact_card_version(
        self,
        fact_card_code: str,
        payload: dict[str, Any],
        *,
        content_sha256: str,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM maitu_workbench_product_fact_cards
                WHERE fact_card_code = %s FOR UPDATE
                """,
                (fact_card_code,),
            )
            card = cursor.fetchone()
            if card is None:
                self.connection.rollback()
                return None
            if card["status"] != "active":
                self.connection.rollback()
                raise MaituWorkbenchConflictError("Archived product fact cards cannot receive new versions")
            cursor.execute(
                """
                SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version
                FROM maitu_workbench_product_fact_card_versions
                WHERE fact_card_id = %s
                """,
                (card["id"],),
            )
            version_number = int(cursor.fetchone()["next_version"])
            approved = bool(payload.get("approve"))
            if approved:
                cursor.execute(
                    """
                    UPDATE maitu_workbench_product_fact_card_versions
                    SET status = 'superseded', updated_at = now()
                    WHERE fact_card_id = %s AND status = 'approved'
                    """,
                    (card["id"],),
                )
            version_code = f"{fact_card_code}-V{version_number:03d}"
            cursor.execute(
                """
                INSERT INTO maitu_workbench_product_fact_card_versions (
                    fact_card_id, fact_card_code, version_code, version_number,
                    status, content, content_sha256, change_reason, created_by,
                    approved_by, approved_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    card["id"],
                    fact_card_code,
                    version_code,
                    version_number,
                    "approved" if approved else "draft",
                    Jsonb(payload["content"]),
                    content_sha256,
                    payload.get("change_reason"),
                    payload.get("created_by"),
                    payload.get("approved_by") if approved else None,
                    datetime.now(UTC) if approved else None,
                ),
            )
            version = cursor.fetchone()
            if approved:
                cursor.execute(
                    """
                    UPDATE maitu_workbench_product_fact_cards
                    SET current_approved_version = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (version_number, card["id"]),
                )
        self.connection.commit()
        return self._serialize(version)

    def approve_product_fact_card_version(
        self,
        fact_card_code: str,
        version_number: int,
        approved_by: str,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT card.id AS fact_card_id, card.status AS card_status, version.*
                FROM maitu_workbench_product_fact_cards AS card
                JOIN maitu_workbench_product_fact_card_versions AS version
                  ON version.fact_card_id = card.id
                WHERE card.fact_card_code = %s AND version.version_number = %s
                FOR UPDATE OF card, version
                """,
                (fact_card_code, version_number),
            )
            version = cursor.fetchone()
            if version is None:
                self.connection.rollback()
                return None
            if version["card_status"] != "active":
                self.connection.rollback()
                raise MaituWorkbenchConflictError("Archived product fact cards cannot be approved")
            if version["status"] == "approved":
                self.connection.commit()
                return self._serialize(version)
            if version["status"] != "draft":
                self.connection.rollback()
                raise MaituWorkbenchConflictError("Only draft fact card versions can be approved")
            cursor.execute(
                """
                UPDATE maitu_workbench_product_fact_card_versions
                SET status = 'superseded', updated_at = now()
                WHERE fact_card_id = %s AND status = 'approved'
                """,
                (version["fact_card_id"],),
            )
            cursor.execute(
                """
                UPDATE maitu_workbench_product_fact_card_versions
                SET status = 'approved', approved_by = %s, approved_at = now(), updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (approved_by, version["id"]),
            )
            approved = cursor.fetchone()
            cursor.execute(
                """
                UPDATE maitu_workbench_product_fact_cards
                SET current_approved_version = %s, updated_at = now()
                WHERE id = %s
                """,
                (version_number, version["fact_card_id"]),
            )
        self.connection.commit()
        return self._serialize(approved)

    def reject_product_fact_card_version(
        self,
        fact_card_code: str,
        version_number: int,
        *,
        rejected_by: str,
        reason: str,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE maitu_workbench_product_fact_card_versions AS version
                SET status = 'rejected', rejected_by = %s, rejected_at = now(),
                    rejection_reason = %s, updated_at = now()
                FROM maitu_workbench_product_fact_cards AS card
                WHERE version.fact_card_id = card.id
                  AND card.fact_card_code = %s
                  AND version.version_number = %s
                  AND version.status = 'draft'
                RETURNING version.*
                """,
                (rejected_by, reason, fact_card_code, version_number),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    """
                    SELECT version.status
                    FROM maitu_workbench_product_fact_card_versions AS version
                    JOIN maitu_workbench_product_fact_cards AS card ON card.id = version.fact_card_id
                    WHERE card.fact_card_code = %s AND version.version_number = %s
                    """,
                    (fact_card_code, version_number),
                )
                existing = cursor.fetchone()
                self.connection.rollback()
                if existing is None:
                    return None
                raise MaituWorkbenchConflictError("Only draft fact card versions can be rejected")
        self.connection.commit()
        return self._serialize(row)

    def resolve_product_fact_card_version(
        self,
        fact_card_code: str,
        version_number: int | None = None,
        *,
        require_approved: bool = True,
    ) -> dict[str, Any] | None:
        where_version = "version.version_number = %s" if version_number is not None else "version.version_number = card.current_approved_version"
        params: list[Any] = [fact_card_code]
        if version_number is not None:
            params.append(version_number)
        if require_approved:
            where_version += " AND version.status = 'approved'"
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT version.*, card.title AS fact_card_title,
                       card.product_code AS bound_product_code, card.status AS fact_card_status
                FROM maitu_workbench_product_fact_cards AS card
                JOIN maitu_workbench_product_fact_card_versions AS version
                  ON version.fact_card_id = card.id
                WHERE card.fact_card_code = %s AND {where_version}
                """,
                tuple(params),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    # Inventory synchronization ----------------------------------------

    def create_inventory_sync_job(
        self,
        payload: dict[str, Any],
        *,
        request_fingerprint: str,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            idempotency_key = payload.get("idempotency_key")
            if idempotency_key:
                cursor.execute(
                    """
                    SELECT * FROM maitu_workbench_inventory_sync_jobs
                    WHERE idempotency_key = %s FOR UPDATE
                    """,
                    (idempotency_key,),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    if existing["request_fingerprint"] != request_fingerprint:
                        self.connection.rollback()
                        raise MaituWorkbenchConflictError("Idempotency key was used with a different sync request")
                    self.connection.commit()
                    return self.get_inventory_sync_job(existing["sync_job_code"]) or {}
            sync_job_code = self._next_code(cursor, "MT-INV-SYNC", "MAITU_WB_INV_SYNC")
            cursor.execute(
                """
                INSERT INTO maitu_workbench_inventory_sync_jobs (
                    sync_job_code, source_system, project_code, sync_mode,
                    request_fingerprint, idempotency_key, config, requested_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    sync_job_code,
                    payload.get("source_system", "maitu"),
                    payload.get("project_code"),
                    payload.get("sync_mode", "full"),
                    request_fingerprint,
                    idempotency_key,
                    Jsonb(payload.get("config") or {}),
                    payload.get("requested_by"),
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row)

    def list_inventory_sync_jobs(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if status:
            clauses.append("job.status = %s")
            values.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.extend((limit, offset))
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT job.*,
                       CASE WHEN snapshot.id IS NULL THEN NULL ELSE to_jsonb(snapshot) END AS snapshot
                FROM maitu_workbench_inventory_sync_jobs AS job
                LEFT JOIN maitu_workbench_inventory_snapshots AS snapshot
                  ON snapshot.id = job.snapshot_id
                {where}
                ORDER BY job.created_at DESC, job.sync_job_code DESC
                LIMIT %s OFFSET %s
                """,
                tuple(values),
            )
            rows = cursor.fetchall()
        return [self._serialize(row) for row in rows]

    def get_inventory_sync_job(self, sync_job_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM maitu_workbench_inventory_sync_jobs WHERE sync_job_code = %s",
                (sync_job_code,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            result = self._serialize(row)
            if row.get("snapshot_id"):
                cursor.execute(
                    "SELECT * FROM maitu_workbench_inventory_snapshots WHERE id = %s",
                    (row["snapshot_id"],),
                )
                snapshot = cursor.fetchone()
                result["snapshot"] = self._serialize(snapshot) if snapshot else None
        return result

    def claim_inventory_sync_job(
        self,
        worker_id: str,
        lease_seconds: int,
        *,
        sync_job_code: str | None = None,
    ) -> dict[str, Any] | None:
        if not worker_id or lease_seconds < 1:
            raise ValueError("worker_id and positive lease_seconds are required")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            code_clause = "AND sync_job_code = %s" if sync_job_code else ""
            params: list[Any] = [sync_job_code] if sync_job_code else []
            cursor.execute(
                f"""
                SELECT *
                FROM maitu_workbench_inventory_sync_jobs
                WHERE (status = 'queued' OR (status = 'running' AND lease_expires_at < now()))
                {code_clause}
                ORDER BY CASE WHEN status = 'running' THEN 0 ELSE 1 END, created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                tuple(params),
            )
            candidate = cursor.fetchone()
            if candidate is None:
                self.connection.commit()
                return None
            cursor.execute(
                """
                UPDATE maitu_workbench_inventory_sync_jobs
                SET status = 'running', claimed_by = %s, lease_token = gen_random_uuid(),
                    lease_expires_at = now() + (%s * interval '1 second'), heartbeat_at = now(),
                    attempt = attempt + CASE WHEN %s = 'running' THEN 1 ELSE 0 END,
                    started_at = COALESCE(started_at, now()), completed_at = NULL,
                    error_code = NULL, error_message = NULL, updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (worker_id, lease_seconds, candidate["status"], candidate["id"]),
            )
            claimed = cursor.fetchone()
        self.connection.commit()
        return self._serialize(claimed)

    def heartbeat_inventory_sync_job(
        self,
        sync_job_code: str,
        worker_id: str,
        lease_token: str,
        lease_seconds: int,
    ) -> dict[str, Any] | None:
        token = self._parse_uuid(lease_token)
        if token is None:
            return None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE maitu_workbench_inventory_sync_jobs
                SET lease_expires_at = now() + (%s * interval '1 second'),
                    heartbeat_at = now(), updated_at = now()
                WHERE sync_job_code = %s AND status = 'running' AND claimed_by = %s
                  AND lease_token = %s AND lease_expires_at > now()
                RETURNING *
                """,
                (lease_seconds, sync_job_code, worker_id, token),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row) if row else None

    def complete_inventory_sync_job(
        self,
        sync_job_code: str,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
        *,
        snapshot_fingerprint: str,
    ) -> dict[str, Any] | None:
        token = self._parse_uuid(lease_token)
        if token is None:
            raise MaituWorkbenchLeaseConflictError("Inventory sync lease is invalid")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_owned_job(
                cursor,
                table="maitu_workbench_inventory_sync_jobs",
                code_column="sync_job_code",
                code=sync_job_code,
                worker_id=worker_id,
                lease_token=token,
            )
            if job is None:
                self.connection.rollback()
                raise MaituWorkbenchLeaseConflictError("Inventory sync lease is not active")
            if job.get("snapshot_id"):
                self.connection.commit()
                return self.get_inventory_sync_job(sync_job_code)
            snapshot_code = self._next_code(cursor, "MT-INV-SNAP", "MAITU_WB_INV_SNAP")
            captured_at = payload.get("captured_at") or datetime.now(UTC)
            items = list(payload.get("items") or [])
            cursor.execute(
                """
                INSERT INTO maitu_workbench_inventory_snapshots (
                    snapshot_code, sync_job_id, source_system, project_code,
                    source_revision, schema_version, quality_status, fingerprint_sha256,
                    item_count, summary, captured_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    snapshot_code,
                    job["id"],
                    job["source_system"],
                    job.get("project_code"),
                    payload.get("source_revision"),
                    payload.get("schema_version", "maitu-inventory-snapshot-v1"),
                    payload.get("quality_status", "complete"),
                    snapshot_fingerprint,
                    len(items),
                    Jsonb(payload.get("summary") or {}),
                    captured_at,
                ),
            )
            snapshot = cursor.fetchone()
            for item in items:
                cursor.execute(
                    """
                    INSERT INTO maitu_workbench_inventory_snapshot_items (
                        snapshot_id, snapshot_code, item_key, material_id, asset_code,
                        title, material_type, category, subtype, availability_status,
                        checksum_sha256, source_material_url, source_cover_url,
                        speaker_id, digital_human_image_id, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        snapshot["id"],
                        snapshot_code,
                        item["item_key"],
                        item.get("material_id"),
                        item.get("asset_code"),
                        item.get("title"),
                        item.get("material_type"),
                        item.get("category"),
                        item.get("subtype"),
                        item.get("availability_status", "available"),
                        item.get("checksum_sha256"),
                        item.get("source_material_url"),
                        item.get("source_cover_url"),
                        item.get("speaker_id"),
                        item.get("digital_human_image_id"),
                        Jsonb(item.get("metadata") or {}),
                    ),
                )
            result_summary = {
                **dict(payload.get("summary") or {}),
                "snapshot_code": snapshot_code,
                "fingerprint_sha256": snapshot_fingerprint,
                "item_count": len(items),
            }
            cursor.execute(
                """
                UPDATE maitu_workbench_inventory_sync_jobs
                SET status = 'succeeded', source_revision = %s, snapshot_id = %s,
                    snapshot_code = %s, result_summary = %s, error_code = NULL,
                    error_message = NULL, claimed_by = NULL, lease_token = NULL,
                    lease_expires_at = NULL, heartbeat_at = NULL,
                    completed_at = now(), updated_at = now()
                WHERE id = %s
                """,
                (
                    payload.get("source_revision"),
                    snapshot["id"],
                    snapshot_code,
                    Jsonb(result_summary),
                    job["id"],
                ),
            )
        self.connection.commit()
        return self.get_inventory_sync_job(sync_job_code)

    def fail_inventory_sync_job(
        self,
        sync_job_code: str,
        worker_id: str,
        lease_token: str,
        *,
        error_code: str,
        error_message: str,
    ) -> dict[str, Any] | None:
        token = self._parse_uuid(lease_token)
        if token is None:
            raise MaituWorkbenchLeaseConflictError("Inventory sync lease is invalid")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_owned_job(
                cursor,
                table="maitu_workbench_inventory_sync_jobs",
                code_column="sync_job_code",
                code=sync_job_code,
                worker_id=worker_id,
                lease_token=token,
            )
            if job is None:
                self.connection.rollback()
                raise MaituWorkbenchLeaseConflictError("Inventory sync lease is not active")
            cursor.execute(
                """
                UPDATE maitu_workbench_inventory_sync_jobs
                SET status = 'failed', error_code = %s, error_message = %s,
                    claimed_by = NULL, lease_token = NULL, lease_expires_at = NULL,
                    heartbeat_at = NULL, completed_at = now(), updated_at = now()
                WHERE id = %s RETURNING *
                """,
                (error_code, error_message, job["id"]),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row)

    def retry_inventory_sync_job(self, sync_job_code: str, requested_by: str | None = None) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE maitu_workbench_inventory_sync_jobs
                SET status = 'queued', attempt = attempt + 1, requested_by = COALESCE(%s, requested_by),
                    claimed_by = NULL, lease_token = NULL, lease_expires_at = NULL,
                    heartbeat_at = NULL, error_code = NULL, error_message = NULL,
                    started_at = NULL, completed_at = NULL, updated_at = now()
                WHERE sync_job_code = %s AND status = 'failed'
                RETURNING *
                """,
                (requested_by, sync_job_code),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    "SELECT status FROM maitu_workbench_inventory_sync_jobs WHERE sync_job_code = %s",
                    (sync_job_code,),
                )
                existing = cursor.fetchone()
                self.connection.rollback()
                if existing is None:
                    return None
                raise MaituWorkbenchConflictError("Only failed inventory sync jobs can be retried")
        self.connection.commit()
        return self._serialize(row)

    def get_inventory_snapshot(self, snapshot_code: str, *, include_items: bool = False) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM maitu_workbench_inventory_snapshots WHERE snapshot_code = %s",
                (snapshot_code,),
            )
            snapshot = cursor.fetchone()
            if snapshot is None:
                return None
            result = self._serialize(snapshot)
            if include_items:
                cursor.execute(
                    """
                    SELECT * FROM maitu_workbench_inventory_snapshot_items
                    WHERE snapshot_id = %s ORDER BY item_key
                    """,
                    (snapshot["id"],),
                )
                result["items"] = [self._serialize(item) for item in cursor.fetchall()]
        return result

    def get_latest_inventory_snapshot(self, source_system: str, project_code: str | None) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM maitu_workbench_inventory_snapshots
                WHERE source_system = %s AND project_code IS NOT DISTINCT FROM %s
                ORDER BY captured_at DESC, created_at DESC LIMIT 1
                """,
                (source_system, project_code),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    def get_inventory_snapshot_item(self, snapshot_code: str, item_key: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT item.*
                FROM maitu_workbench_inventory_snapshot_items AS item
                JOIN maitu_workbench_inventory_snapshots AS snapshot ON snapshot.id = item.snapshot_id
                WHERE snapshot.snapshot_code = %s AND item.item_key = %s
                """,
                (snapshot_code, item_key),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    # Workbench runs and plan revisions --------------------------------

    def resolve_published_reference_template(
        self,
        template_code: str,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT publication.template_code, template.name AS template_name,
                       publication.revision_number, publication.projection_contract,
                       publication.projection_payload, publication.projection_fingerprint,
                       publication.projection_ready, publication.manual_review_required,
                       publication.published_at
                FROM live_room_template_publications AS publication
                JOIN live_room_templates AS template ON template.id = publication.template_id
                JOIN live_room_template_revisions AS revision
                  ON revision.id = publication.revision_id
                WHERE publication.template_code = %s
                  AND publication.retracted_at IS NULL
                  AND template.archived_at IS NULL
                  AND template.published_revision_id = publication.revision_id
                  AND revision.status = 'published'
                  AND revision.revision_number = publication.revision_number
                ORDER BY publication.published_at DESC
                LIMIT 1
                """,
                (template_code,),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    def create_run(
        self,
        payload: dict[str, Any],
        *,
        fact_card_version: dict[str, Any],
        inventory_snapshot: dict[str, Any],
        reference_template: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        reference = reference_template or {}
        with self.connection.cursor(row_factory=dict_row) as cursor:
            run_code = self._next_code(cursor, "MT-WB-RUN", "MAITU_WB_RUN")
            cursor.execute(
                """
                INSERT INTO maitu_workbench_runs (
                    run_code, title, topic, fact_card_version_id, fact_card_version_code,
                    inventory_snapshot_id, inventory_snapshot_code, target_live_room_id,
                    target_duration_minutes, build_mode, include_default_host,
                    max_candidates_per_need, canvas_width, canvas_height,
                    reference_template_code, reference_template_revision_number,
                    reference_template_projection_fingerprint, reference_template_snapshot,
                    created_by
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING *
                """,
                (
                    run_code,
                    payload["title"],
                    payload["topic"],
                    fact_card_version["id"],
                    fact_card_version["version_code"],
                    inventory_snapshot["id"],
                    inventory_snapshot["snapshot_code"],
                    payload.get("target_live_room_id"),
                    payload.get("target_duration_minutes", 1),
                    payload.get("build_mode", "strict"),
                    payload.get("include_default_host", True),
                    payload.get("max_candidates_per_need", 1),
                    payload.get("canvas_width", 1080),
                    payload.get("canvas_height", 1920),
                    reference.get("template_code"),
                    reference.get("revision_number"),
                    reference.get("projection_fingerprint"),
                    Jsonb(reference["snapshot"]) if reference.get("snapshot") is not None else None,
                    payload.get("created_by"),
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self.get_run(run_code) or self._serialize(row)

    def list_runs(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where = "WHERE run.status = %s" if status else ""
        params: list[Any] = [status] if status else []
        params.extend((limit, offset))
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT run.*, version.fact_card_code,
                       version.version_number AS fact_card_version_number
                FROM maitu_workbench_runs AS run
                JOIN maitu_workbench_product_fact_card_versions AS version
                  ON version.id = run.fact_card_version_id
                {where}
                ORDER BY run.created_at DESC, run.run_code DESC LIMIT %s OFFSET %s
                """,
                tuple(params),
            )
            rows = cursor.fetchall()
        return [self._serialize(row) for row in rows]

    def get_run(self, run_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM maitu_workbench_runs WHERE run_code = %s", (run_code,))
            run = cursor.fetchone()
            if run is None:
                return None
            result = self._serialize(run)
            cursor.execute(
                "SELECT * FROM maitu_workbench_product_fact_card_versions WHERE id = %s",
                (run["fact_card_version_id"],),
            )
            fact_card_version = self._serialize(cursor.fetchone() or {})
            result["fact_card_version"] = fact_card_version
            result["fact_card_code"] = fact_card_version.get("fact_card_code")
            result["fact_card_version_number"] = fact_card_version.get("version_number")
            cursor.execute(
                "SELECT * FROM maitu_workbench_inventory_snapshots WHERE id = %s",
                (run["inventory_snapshot_id"],),
            )
            result["inventory_snapshot"] = self._serialize(cursor.fetchone() or {})
            cursor.execute(
                """
                SELECT * FROM maitu_workbench_plan_revisions
                WHERE run_id = %s AND revision_number = %s
                """,
                (run["id"], run["active_plan_revision"]),
            )
            active_plan = cursor.fetchone()
            result["active_plan"] = self._serialize(active_plan) if active_plan else None
            cursor.execute(
                """
                SELECT * FROM maitu_workbench_preflights
                WHERE run_id = %s ORDER BY preflight_number DESC LIMIT 1
                """,
                (run["id"],),
            )
            preflight = cursor.fetchone()
            result["latest_preflight"] = self._serialize(preflight) if preflight else None
        return result

    def update_run_target_live_room(
        self,
        run_code: str,
        target_live_room_id: str,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM maitu_workbench_runs WHERE run_code = %s FOR UPDATE",
                (run_code,),
            )
            run = cursor.fetchone()
            if run is None:
                self.connection.rollback()
                return None
            if run["status"] in {"planning", "execution_queued", "executing", "completed"}:
                self.connection.rollback()
                raise MaituWorkbenchConflictError(
                    "Target room cannot change while planning or after draft execution starts"
                )
            if run.get("target_live_room_id") == target_live_room_id:
                self.connection.commit()
                return self.get_run(run_code)
            next_status = "replan_required" if int(run["active_plan_revision"]) > 0 else "draft"
            cursor.execute(
                """
                UPDATE maitu_workbench_runs
                SET target_live_room_id = %s, status = %s, error_code = NULL,
                    error_message = NULL, completed_at = NULL, updated_at = now()
                WHERE id = %s
                """,
                (target_live_room_id, next_status, run["id"]),
            )
        self.connection.commit()
        return self.get_run(run_code)

    def mark_run_planning(self, run_code: str, *, expected_revision: int) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE maitu_workbench_runs
                SET status = 'planning', error_code = NULL, error_message = NULL, updated_at = now()
                WHERE run_code = %s AND active_plan_revision = %s
                  AND status <> 'planning'
                  AND status NOT IN ('execution_queued', 'executing', 'completed')
                RETURNING *
                """,
                (run_code, expected_revision),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute("SELECT 1 FROM maitu_workbench_runs WHERE run_code = %s", (run_code,))
                exists = cursor.fetchone() is not None
                self.connection.rollback()
                if not exists:
                    return None
                raise MaituWorkbenchConflictError("Run changed or cannot be planned from its current state")
        self.connection.commit()
        return self._serialize(row)

    def mark_run_failed(
        self,
        run_code: str,
        error_code: str,
        error_message: str,
        *,
        expected_revision: int,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE maitu_workbench_runs
                SET status = 'failed', error_code = %s, error_message = %s, updated_at = now()
                WHERE run_code = %s AND active_plan_revision = %s AND status = 'planning'
                RETURNING *
                """,
                (error_code, error_message, run_code, expected_revision),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row) if row else None

    def create_plan_revision(
        self,
        run_code: str,
        *,
        expected_revision: int,
        trigger_type: str,
        status: str,
        fact_card_version: dict[str, Any],
        inventory_snapshot: dict[str, Any],
        source_build_plan_code: str | None,
        input_fingerprint: str,
        generation_prompt_version: str,
        generation_input_fingerprint: str,
        generation_output_fingerprint: str,
        pipeline_source: str,
        pipeline_output: dict[str, Any],
        gap_report: dict[str, Any],
        blocked_reasons: list[str],
        requirements: list[dict[str, Any]],
        reason: str | None,
        created_by: str | None,
        generation_strategy_revision: str | None = None,
        generation_invocation_evidence_ref: str | None = None,
        generation_provider: str | None = None,
        generation_requested_model: str | None = None,
        generation_actual_model: str | None = None,
        generation_request_id: str | None = None,
        generation_usage: dict[str, Any] | None = None,
        generation_latency_ms: int | None = None,
    ) -> dict[str, Any]:
        legacy_contract = generation_strategy_revision is None
        strategy_revision = (
            "legacy.maitu-plan.v1"
            if legacy_contract
            else generation_strategy_revision
        )
        if not legacy_contract:
            generation_provider = None
            generation_requested_model = None
            generation_actual_model = None
            generation_request_id = None
            generation_usage = {}
            generation_latency_ms = None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM maitu_workbench_runs WHERE run_code = %s FOR UPDATE",
                (run_code,),
            )
            run = cursor.fetchone()
            if run is None:
                self.connection.rollback()
                raise KeyError(run_code)
            if int(run["active_plan_revision"]) != expected_revision or run["status"] != "planning":
                self.connection.rollback()
                raise MaituWorkbenchConflictError("Run revision changed while planning")
            revision_number = expected_revision + 1
            cursor.execute(
                """
                UPDATE maitu_workbench_plan_revisions
                SET status = 'superseded', superseded_at = now()
                WHERE run_id = %s AND status IN ('ready', 'blocked', 'failed')
                """,
                (run["id"],),
            )
            base_code = self._next_code(cursor, "MT-WB-PLAN", "MAITU_WB_PLAN")
            revision_code = f"{base_code}-R{revision_number:03d}"
            cursor.execute(
                """
                INSERT INTO maitu_workbench_plan_revisions (
                    plan_revision_code, run_id, run_code, revision_number, trigger_type,
                    status, fact_card_version_id, fact_card_version_code,
                    inventory_snapshot_id, inventory_snapshot_code, source_build_plan_code,
                    input_fingerprint, generation_strategy_revision,
                    generation_invocation_evidence_ref,
                    generation_provider, generation_requested_model,
                    generation_actual_model, generation_prompt_version, generation_request_id,
                    generation_input_fingerprint, generation_output_fingerprint,
                    generation_usage, generation_latency_ms, pipeline_source, pipeline_output,
                    gap_report, blocked_reasons, reason, created_by
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING *
                """,
                (
                    revision_code,
                    run["id"],
                    run_code,
                    revision_number,
                    trigger_type,
                    status,
                    fact_card_version["id"],
                    fact_card_version["version_code"],
                    inventory_snapshot["id"],
                    inventory_snapshot["snapshot_code"],
                    source_build_plan_code,
                    input_fingerprint,
                    strategy_revision,
                    generation_invocation_evidence_ref,
                    generation_provider,
                    generation_requested_model,
                    generation_actual_model,
                    generation_prompt_version,
                    generation_request_id,
                    generation_input_fingerprint,
                    generation_output_fingerprint,
                    Jsonb(generation_usage or {}),
                    generation_latency_ms,
                    pipeline_source,
                    Jsonb(pipeline_output),
                    Jsonb(gap_report),
                    Jsonb(blocked_reasons),
                    reason,
                    created_by,
                ),
            )
            plan = cursor.fetchone()
            for requirement_payload in requirements:
                requirement = dict(requirement_payload)
                requirement_code = self._next_code(cursor, "MT-WB-REQ", "MAITU_WB_REQ")
                initial_decision = requirement.pop("initial_decision", None)
                current_decision_revision = 1 if initial_decision else 0
                cursor.execute(
                    """
                    INSERT INTO maitu_workbench_material_requirements (
                        requirement_code, requirement_key, run_id, run_code,
                        plan_revision_id, plan_revision_number, scene_index, scene_name,
                        need_index, need_type, required_category, accepted_asset_types,
                        description, keywords, priority, is_required, status,
                        current_decision_revision, pipeline_selection
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        requirement_code,
                        requirement["requirement_key"],
                        run["id"],
                        run_code,
                        plan["id"],
                        revision_number,
                        requirement["scene_index"],
                        requirement["scene_name"],
                        requirement["need_index"],
                        requirement["need_type"],
                        requirement["required_category"],
                        Jsonb(requirement.get("accepted_asset_types") or []),
                        requirement.get("description") or "",
                        Jsonb(requirement.get("keywords") or []),
                        requirement.get("priority", "medium"),
                        bool(requirement.get("is_required")),
                        requirement.get("status", "pending"),
                        current_decision_revision,
                        Jsonb(requirement.get("pipeline_selection") or {}),
                    ),
                )
                requirement_id = cursor.fetchone()["id"]
                if initial_decision:
                    decision_code = self._next_code(cursor, "MT-WB-DEC", "MAITU_WB_DEC")
                    cursor.execute(
                        """
                        INSERT INTO maitu_workbench_material_decisions (
                            decision_code, requirement_id, requirement_code, revision_number,
                            decision, selected_asset_code, selected_material_key, reason,
                            decision_source, decided_by, inventory_snapshot_id
                        )
                        VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            decision_code,
                            requirement_id,
                            requirement_code,
                            initial_decision["decision"],
                            initial_decision.get("selected_asset_code"),
                            initial_decision.get("selected_material_key"),
                            initial_decision["reason"],
                            initial_decision.get("decision_source", "pipeline_auto"),
                            initial_decision.get("decided_by"),
                            inventory_snapshot["id"],
                        ),
                    )
            run_status = "ready" if status == "ready" else "blocked"
            cursor.execute(
                """
                UPDATE maitu_workbench_runs
                SET status = %s, fact_card_version_id = %s, fact_card_version_code = %s,
                    inventory_snapshot_id = %s, inventory_snapshot_code = %s,
                    active_plan_revision = %s, error_code = NULL, error_message = NULL,
                    updated_at = now()
                WHERE id = %s
                """,
                (
                    run_status,
                    fact_card_version["id"],
                    fact_card_version["version_code"],
                    inventory_snapshot["id"],
                    inventory_snapshot["snapshot_code"],
                    revision_number,
                    run["id"],
                ),
            )
        self.connection.commit()
        return self.get_plan_revision(run_code, revision_number) or self._serialize(plan)

    def get_plan_revision(self, run_code: str, revision_number: int) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM maitu_workbench_plan_revisions
                WHERE run_code = %s AND revision_number = %s
                """,
                (run_code, revision_number),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    def list_plan_revisions(self, run_code: str) -> list[dict[str, Any]] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT 1 FROM maitu_workbench_runs WHERE run_code = %s", (run_code,))
            if cursor.fetchone() is None:
                return None
            cursor.execute(
                """
                SELECT * FROM maitu_workbench_plan_revisions
                WHERE run_code = %s ORDER BY revision_number DESC
                """,
                (run_code,),
            )
            rows = cursor.fetchall()
        return [self._serialize(row) for row in rows]

    def list_material_requirements(self, run_code: str, *, active_only: bool = True) -> list[dict[str, Any]] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM maitu_workbench_runs WHERE run_code = %s", (run_code,))
            run = cursor.fetchone()
            if run is None:
                return None
            revision_clause = "AND req.plan_revision_number = %s" if active_only else ""
            params: list[Any] = [run["id"]]
            if active_only:
                params.append(run["active_plan_revision"])
            cursor.execute(
                f"""
                SELECT req.* FROM maitu_workbench_material_requirements AS req
                WHERE req.run_id = %s {revision_clause}
                ORDER BY req.plan_revision_number DESC, req.scene_index, req.need_index
                """,
                tuple(params),
            )
            requirements = cursor.fetchall()
            result: list[dict[str, Any]] = []
            for requirement in requirements:
                item = self._serialize(requirement)
                cursor.execute(
                    """
                    SELECT * FROM maitu_workbench_material_decisions
                    WHERE requirement_id = %s ORDER BY revision_number
                    """,
                    (requirement["id"],),
                )
                item["decisions"] = [self._serialize(row) for row in cursor.fetchall()]
                result.append(item)
        return result

    def get_manual_decision_overrides(self, run_code: str, revision_number: int) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT DISTINCT ON (req.id)
                       req.requirement_key, req.scene_index, req.need_type,
                       req.required_category,
                       req.plan_revision_number AS requirement_plan_revision_number,
                       decision.*
                FROM maitu_workbench_material_requirements AS req
                JOIN maitu_workbench_material_decisions AS decision
                  ON decision.requirement_id = req.id
                WHERE req.run_code = %s AND req.plan_revision_number <= %s
                  AND decision.decision_source IN ('manual', 'carried_forward')
                ORDER BY req.id, decision.revision_number DESC
                """,
                (run_code, revision_number),
            )
            rows = cursor.fetchall()
        return [self._serialize(row) for row in rows]

    def create_material_decision(
        self,
        run_code: str,
        requirement_code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT req.*, run.active_plan_revision, run.inventory_snapshot_id
                FROM maitu_workbench_material_requirements AS req
                JOIN maitu_workbench_runs AS run ON run.id = req.run_id
                WHERE req.run_code = %s AND req.requirement_code = %s
                FOR UPDATE OF req, run
                """,
                (run_code, requirement_code),
            )
            requirement = cursor.fetchone()
            if requirement is None:
                self.connection.rollback()
                return None
            if requirement["plan_revision_number"] != requirement["active_plan_revision"]:
                self.connection.rollback()
                raise MaituWorkbenchConflictError("Decisions can only change active-plan requirements")
            revision_number = int(requirement["current_decision_revision"]) + 1
            decision_code = self._next_code(cursor, "MT-WB-DEC", "MAITU_WB_DEC")
            cursor.execute(
                """
                INSERT INTO maitu_workbench_material_decisions (
                    decision_code, requirement_id, requirement_code, revision_number,
                    decision, selected_asset_code, selected_material_key, reason,
                    decision_source, decided_by, inventory_snapshot_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'manual', %s, %s)
                RETURNING *
                """,
                (
                    decision_code,
                    requirement["id"],
                    requirement_code,
                    revision_number,
                    payload["decision"],
                    payload.get("selected_asset_code"),
                    payload.get("selected_material_key"),
                    payload["reason"],
                    payload.get("decided_by"),
                    requirement["inventory_snapshot_id"],
                ),
            )
            decision = cursor.fetchone()
            cursor.execute(
                """
                UPDATE maitu_workbench_material_requirements
                SET status = %s, current_decision_revision = %s, updated_at = now()
                WHERE id = %s
                """,
                (payload["decision"], revision_number, requirement["id"]),
            )
            cursor.execute(
                """
                UPDATE maitu_workbench_runs
                SET status = 'replan_required', error_code = NULL, error_message = NULL, updated_at = now()
                WHERE id = %s
                """,
                (requirement["run_id"],),
            )
        self.connection.commit()
        return self._serialize(decision)

    def get_asset_selection(self, asset_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT asset_code, asset_type, title, original_filename, display_code,
                       local_file_code, local_relative_path, browser_use_hint,
                       maitu_material_id, source_material_type, source_material_url,
                       source_cover_url, speaker_id, digital_human_image_id,
                       maitu_category, status
                FROM assets
                WHERE asset_code = %s AND deleted_at IS NULL
                """,
                (asset_code,),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    # Preflight ---------------------------------------------------------

    def create_preflight(
        self,
        run_code: str,
        *,
        expected_plan_revision: int,
        status: str,
        input_fingerprint: str,
        checks: list[dict[str, Any]],
        blocked_reasons: list[str],
        performed_by: str | None,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM maitu_workbench_runs WHERE run_code = %s FOR UPDATE", (run_code,))
            run = cursor.fetchone()
            if run is None:
                self.connection.rollback()
                raise KeyError(run_code)
            if int(run["active_plan_revision"]) != expected_plan_revision:
                self.connection.rollback()
                raise MaituWorkbenchConflictError("Preflight plan revision is stale")
            cursor.execute(
                """
                SELECT * FROM maitu_workbench_plan_revisions
                WHERE run_id = %s AND revision_number = %s
                """,
                (run["id"], expected_plan_revision),
            )
            plan = cursor.fetchone()
            if plan is None:
                self.connection.rollback()
                raise MaituWorkbenchConflictError("Active plan revision is missing")
            cursor.execute(
                """
                SELECT COALESCE(MAX(preflight_number), 0) + 1 AS next_number
                FROM maitu_workbench_preflights WHERE run_id = %s
                """,
                (run["id"],),
            )
            preflight_number = int(cursor.fetchone()["next_number"])
            preflight_code = self._next_code(cursor, "MT-WB-PREF", "MAITU_WB_PREF")
            cursor.execute(
                """
                INSERT INTO maitu_workbench_preflights (
                    preflight_code, run_id, run_code, plan_revision_id,
                    plan_revision_number, preflight_number, status, input_fingerprint,
                    checks, blocked_reasons, performed_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    preflight_code,
                    run["id"],
                    run_code,
                    plan["id"],
                    expected_plan_revision,
                    preflight_number,
                    status,
                    input_fingerprint,
                    Jsonb(checks),
                    Jsonb(blocked_reasons),
                    performed_by,
                ),
            )
            preflight = cursor.fetchone()
            cursor.execute(
                """
                UPDATE maitu_workbench_runs
                SET status = %s, updated_at = now()
                WHERE id = %s
                """,
                ("preflight_passed" if status == "passed" else "blocked", run["id"]),
            )
        self.connection.commit()
        return self._serialize(preflight)

    def get_latest_preflight(self, run_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM maitu_workbench_preflights
                WHERE run_code = %s ORDER BY preflight_number DESC LIMIT 1
                """,
                (run_code,),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    # Draft execution jobs ---------------------------------------------

    def create_draft_execution_job(
        self,
        run_code: str,
        *,
        expected_plan_revision: int,
        input_fingerprint: str,
        payload: dict[str, Any],
        idempotency_key: str | None,
        queued_by: str | None,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            if idempotency_key:
                cursor.execute(
                    """
                    SELECT * FROM maitu_workbench_draft_execution_jobs
                    WHERE idempotency_key = %s FOR UPDATE
                    """,
                    (idempotency_key,),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    if existing["input_fingerprint"] != input_fingerprint:
                        self.connection.rollback()
                        raise MaituWorkbenchConflictError("Idempotency key was used for another draft execution")
                    self.connection.commit()
                    return self._serialize(existing)
            cursor.execute("SELECT * FROM maitu_workbench_runs WHERE run_code = %s FOR UPDATE", (run_code,))
            run = cursor.fetchone()
            if run is None:
                self.connection.rollback()
                raise KeyError(run_code)
            if run["status"] != "preflight_passed" or run["active_plan_revision"] != expected_plan_revision:
                self.connection.rollback()
                raise MaituWorkbenchConflictError("A current passed preflight is required")
            cursor.execute(
                """
                SELECT * FROM maitu_workbench_plan_revisions
                WHERE run_id = %s AND revision_number = %s AND status = 'ready'
                """,
                (run["id"], expected_plan_revision),
            )
            plan = cursor.fetchone()
            cursor.execute(
                """
                SELECT * FROM maitu_workbench_preflights
                WHERE run_id = %s AND plan_revision_number = %s AND status = 'passed'
                ORDER BY preflight_number DESC LIMIT 1
                """,
                (run["id"], expected_plan_revision),
            )
            preflight = cursor.fetchone()
            if plan is None or preflight is None:
                self.connection.rollback()
                raise MaituWorkbenchConflictError("Ready plan and passed preflight are required")
            execution_job_code = self._next_code(cursor, "MT-WB-EXEC", "MAITU_WB_EXEC")
            cursor.execute(
                """
                INSERT INTO maitu_workbench_draft_execution_jobs (
                    execution_job_code, run_id, run_code, plan_revision_id,
                    plan_revision_number, preflight_id, preflight_code, input_fingerprint,
                    idempotency_key, payload, ready_for_go_live, queued_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, false, %s)
                RETURNING *
                """,
                (
                    execution_job_code,
                    run["id"],
                    run_code,
                    plan["id"],
                    expected_plan_revision,
                    preflight["id"],
                    preflight["preflight_code"],
                    input_fingerprint,
                    idempotency_key,
                    Jsonb(payload),
                    queued_by,
                ),
            )
            job = cursor.fetchone()
            cursor.execute(
                "UPDATE maitu_workbench_runs SET status = 'execution_queued', updated_at = now() WHERE id = %s",
                (run["id"],),
            )
        self.connection.commit()
        return self._serialize(job)

    def get_draft_execution_job(self, execution_job_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM maitu_workbench_draft_execution_jobs WHERE execution_job_code = %s",
                (execution_job_code,),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    def claim_draft_execution_job(
        self,
        worker_id: str,
        lease_seconds: int,
        *,
        execution_job_code: str | None = None,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            code_clause = "AND execution_job_code = %s" if execution_job_code else ""
            params: list[Any] = [execution_job_code] if execution_job_code else []
            cursor.execute(
                f"""
                SELECT * FROM maitu_workbench_draft_execution_jobs
                WHERE (status = 'queued' OR (status = 'running' AND lease_expires_at < now()))
                {code_clause}
                ORDER BY CASE WHEN status = 'running' THEN 0 ELSE 1 END, created_at
                FOR UPDATE SKIP LOCKED LIMIT 1
                """,
                tuple(params),
            )
            candidate = cursor.fetchone()
            if candidate is None:
                self.connection.commit()
                return None
            cursor.execute(
                """
                UPDATE maitu_workbench_draft_execution_jobs
                SET status = 'running', claimed_by = %s, lease_token = gen_random_uuid(),
                    lease_expires_at = now() + (%s * interval '1 second'), heartbeat_at = now(),
                    attempt = attempt + CASE WHEN %s = 'running' THEN 1 ELSE 0 END,
                    started_at = COALESCE(started_at, now()), completed_at = NULL,
                    error_code = NULL, error_message = NULL, updated_at = now()
                WHERE id = %s RETURNING *
                """,
                (worker_id, lease_seconds, candidate["status"], candidate["id"]),
            )
            claimed = cursor.fetchone()
            cursor.execute(
                "UPDATE maitu_workbench_runs SET status = 'executing', updated_at = now() WHERE id = %s",
                (candidate["run_id"],),
            )
        self.connection.commit()
        return self._serialize(claimed)

    def heartbeat_draft_execution_job(
        self,
        execution_job_code: str,
        worker_id: str,
        lease_token: str,
        lease_seconds: int,
    ) -> dict[str, Any] | None:
        token = self._parse_uuid(lease_token)
        if token is None:
            return None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE maitu_workbench_draft_execution_jobs
                SET lease_expires_at = now() + (%s * interval '1 second'),
                    heartbeat_at = now(), updated_at = now()
                WHERE execution_job_code = %s AND status = 'running' AND claimed_by = %s
                  AND lease_token = %s AND lease_expires_at > now()
                RETURNING *
                """,
                (lease_seconds, execution_job_code, worker_id, token),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row) if row else None

    def complete_draft_execution_job(
        self,
        execution_job_code: str,
        worker_id: str,
        lease_token: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        token = self._parse_uuid(lease_token)
        if token is None:
            raise MaituWorkbenchLeaseConflictError("Draft execution lease is invalid")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_owned_job(
                cursor,
                table="maitu_workbench_draft_execution_jobs",
                code_column="execution_job_code",
                code=execution_job_code,
                worker_id=worker_id,
                lease_token=token,
            )
            if job is None:
                self.connection.rollback()
                raise MaituWorkbenchLeaseConflictError("Draft execution lease is not active")
            cursor.execute(
                """
                UPDATE maitu_workbench_draft_execution_jobs
                SET status = 'succeeded', result = %s, claimed_by = NULL,
                    lease_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
                    completed_at = now(), updated_at = now()
                WHERE id = %s RETURNING *
                """,
                (Jsonb(result), job["id"]),
            )
            completed = cursor.fetchone()
            cursor.execute(
                """
                UPDATE maitu_workbench_runs
                SET status = 'completed', completed_at = now(), error_code = NULL,
                    error_message = NULL, updated_at = now()
                WHERE id = %s
                """,
                (job["run_id"],),
            )
        self.connection.commit()
        return self._serialize(completed)

    def fail_draft_execution_job(
        self,
        execution_job_code: str,
        worker_id: str,
        lease_token: str,
        *,
        error_code: str,
        error_message: str,
    ) -> dict[str, Any]:
        token = self._parse_uuid(lease_token)
        if token is None:
            raise MaituWorkbenchLeaseConflictError("Draft execution lease is invalid")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_owned_job(
                cursor,
                table="maitu_workbench_draft_execution_jobs",
                code_column="execution_job_code",
                code=execution_job_code,
                worker_id=worker_id,
                lease_token=token,
            )
            if job is None:
                self.connection.rollback()
                raise MaituWorkbenchLeaseConflictError("Draft execution lease is not active")
            cursor.execute(
                """
                UPDATE maitu_workbench_draft_execution_jobs
                SET status = 'failed', error_code = %s, error_message = %s,
                    claimed_by = NULL, lease_token = NULL, lease_expires_at = NULL,
                    heartbeat_at = NULL, completed_at = now(), updated_at = now()
                WHERE id = %s RETURNING *
                """,
                (error_code, error_message, job["id"]),
            )
            failed = cursor.fetchone()
            cursor.execute(
                """
                UPDATE maitu_workbench_runs
                SET status = 'failed', error_code = %s, error_message = %s, updated_at = now()
                WHERE id = %s
                """,
                (error_code, error_message, job["run_id"]),
            )
        self.connection.commit()
        return self._serialize(failed)

    def retry_draft_execution_job(
        self,
        execution_job_code: str,
        requested_by: str | None = None,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM maitu_workbench_draft_execution_jobs
                WHERE execution_job_code = %s
                FOR UPDATE
                """,
                (execution_job_code,),
            )
            failed_job = cursor.fetchone()
            if failed_job is None:
                self.connection.commit()
                return None
            if failed_job.get("status") != "failed":
                self.connection.rollback()
                raise MaituWorkbenchConflictError("Only failed draft execution jobs can be retried")
            payload = failed_job.get("payload") if isinstance(failed_job.get("payload"), dict) else {}
            embedded_plan = payload.get("build_plan") if isinstance(payload.get("build_plan"), dict) else {}
            build_plan_code = str(embedded_plan.get("build_plan_code") or "").strip()
            if build_plan_code:
                cursor.execute(
                    """
                    SELECT * FROM maitu_live_room_build_plan_executions
                    WHERE build_plan_code = %s
                      AND checkpoint_contract = 'script_layout_checkpoint_v1'
                      AND finalized_at IS NOT NULL
                      AND execution_status IN ('completed', 'completed_with_manual_review')
                      AND deleted_at IS NULL
                    ORDER BY finalized_at DESC
                    LIMIT 1
                    """,
                    (build_plan_code,),
                )
                finalized = cursor.fetchone()
                if finalized is not None:
                    details = finalized.get("details") if isinstance(finalized.get("details"), dict) else {}
                    checkpoint_status = str(finalized["execution_status"])
                    manual_review_required = checkpoint_status == "completed_with_manual_review"
                    if (
                        details.get("ready_for_go_live") is False
                        and bool(details.get("manual_review_required")) is manual_review_required
                    ):
                        target_live_room_id = str(
                            details.get("target_live_room_id")
                            or embedded_plan.get("target_live_room_id")
                            or ""
                        ).strip()
                        finalized_at = finalized.get("finalized_at")
                        checkpoint_result = {
                            "execution_code": finalized["execution_code"],
                            "build_plan_code": build_plan_code,
                            "execution_status": checkpoint_status,
                            "expected_operation_count": finalized.get("expected_operation_count"),
                            "result_summary": finalized.get("result_summary"),
                            "manual_review_required": manual_review_required,
                            "ready_for_go_live": False,
                            "finalized_at": finalized_at.isoformat() if finalized_at is not None else None,
                        }
                        recovered_result = {
                            "status": checkpoint_status,
                            "target_live_room_id": target_live_room_id,
                            "worker_result": {
                                "status": checkpoint_status,
                                "summary": finalized.get("result_summary"),
                                "operation_count": finalized.get("expected_operation_count"),
                                "manual_review_required": manual_review_required,
                                "ready_for_go_live": False,
                                "recovered_from_finalized_checkpoint": True,
                            },
                            "checkpoint_result": checkpoint_result,
                            "ready_for_go_live": False,
                        }
                        cursor.execute(
                            """
                            UPDATE maitu_workbench_draft_execution_jobs
                            SET status = 'succeeded', result = %s, queued_by = COALESCE(%s, queued_by),
                                claimed_by = NULL, lease_token = NULL, lease_expires_at = NULL,
                                heartbeat_at = NULL, error_code = NULL, error_message = NULL,
                                completed_at = now(), updated_at = now()
                            WHERE id = %s
                            RETURNING *
                            """,
                            (Jsonb(recovered_result), requested_by, failed_job["id"]),
                        )
                        recovered_job = cursor.fetchone()
                        cursor.execute(
                            """
                            UPDATE maitu_workbench_runs
                            SET status = 'completed', completed_at = now(), error_code = NULL,
                                error_message = NULL, updated_at = now()
                            WHERE id = %s
                            """,
                            (failed_job["run_id"],),
                        )
                        self.connection.commit()
                        return self._serialize(recovered_job)
            cursor.execute(
                """
                UPDATE maitu_workbench_draft_execution_jobs
                SET status = 'queued', attempt = attempt + 1, queued_by = COALESCE(%s, queued_by),
                    result = '{}'::jsonb, claimed_by = NULL, lease_token = NULL,
                    lease_expires_at = NULL, heartbeat_at = NULL, error_code = NULL,
                    error_message = NULL, started_at = NULL, completed_at = NULL, updated_at = now()
                WHERE id = %s AND status = 'failed'
                RETURNING *
                """,
                (requested_by, failed_job["id"]),
            )
            job = cursor.fetchone()
            if job is None:
                self.connection.rollback()
                raise MaituWorkbenchConflictError("Draft execution job changed during retry")
            cursor.execute(
                """
                UPDATE maitu_workbench_runs
                SET status = 'execution_queued', error_code = NULL, error_message = NULL,
                    completed_at = NULL, updated_at = now()
                WHERE id = %s
                """,
                (job["run_id"],),
            )
        self.connection.commit()
        return self._serialize(job)

    def cancel_draft_execution_job(self, execution_job_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE maitu_workbench_draft_execution_jobs
                SET status = 'cancelled', completed_at = now(), updated_at = now()
                WHERE execution_job_code = %s AND status = 'queued'
                RETURNING *
                """,
                (execution_job_code,),
            )
            job = cursor.fetchone()
            if job is None:
                cursor.execute(
                    "SELECT status FROM maitu_workbench_draft_execution_jobs WHERE execution_job_code = %s",
                    (execution_job_code,),
                )
                existing = cursor.fetchone()
                self.connection.rollback()
                if existing is None:
                    return None
                raise MaituWorkbenchConflictError("Only queued draft execution jobs can be cancelled")
            cursor.execute(
                "UPDATE maitu_workbench_runs SET status = 'preflight_passed', updated_at = now() WHERE id = %s",
                (job["run_id"],),
            )
        self.connection.commit()
        return self._serialize(job)

    # Selected video material analysis ---------------------------------

    def synchronize_selected_video_analyses(self, run_code: str) -> list[dict[str, Any]] | None:
        """Create one durable analysis task per selected, snapshot-bound video asset."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT id, inventory_snapshot_id FROM maitu_workbench_runs WHERE run_code = %s",
                (run_code,),
            )
            run = cursor.fetchone()
            if run is None:
                return None
            cursor.execute(
                """
                WITH selected AS (
                    SELECT req.id AS requirement_id, req.requirement_code,
                           decision.selected_asset_code, decision.selected_material_key
                    FROM maitu_workbench_material_requirements AS req
                    JOIN maitu_workbench_runs AS active_run ON active_run.id = req.run_id
                    JOIN LATERAL (
                        SELECT material_decision.*
                        FROM maitu_workbench_material_decisions AS material_decision
                        WHERE material_decision.requirement_id = req.id
                        ORDER BY material_decision.revision_number DESC
                        LIMIT 1
                    ) AS decision ON decision.decision = 'selected'
                    WHERE active_run.run_code = %s
                      AND req.plan_revision_number = active_run.active_plan_revision
                      AND req.status = 'selected'
                ), resolved AS (
                    SELECT selected.requirement_id, selected.requirement_code,
                           COALESCE(selected.selected_asset_code, item.asset_code) AS asset_code,
                           item.id AS inventory_item_id, item.title AS inventory_title,
                           item.material_type, item.checksum_sha256 AS inventory_fingerprint,
                           item.metadata AS inventory_metadata
                    FROM selected
                    LEFT JOIN maitu_workbench_inventory_snapshot_items AS item
                      ON item.snapshot_id = %s
                     AND (
                         (selected.selected_material_key IS NOT NULL
                          AND item.item_key = selected.selected_material_key)
                         OR (selected.selected_asset_code IS NOT NULL
                             AND item.asset_code = selected.selected_asset_code)
                     )
                )
                SELECT DISTINCT ON (resolved.asset_code)
                       resolved.requirement_id, resolved.requirement_code, resolved.asset_code,
                       COALESCE(asset.title, resolved.inventory_title, resolved.asset_code) AS asset_title,
                       COALESCE(resolved.inventory_fingerprint, asset.checksum_sha256) AS asset_fingerprint,
                       COALESCE(asset.local_relative_path,
                                resolved.inventory_metadata ->> 'local_relative_path') AS source_relative_path,
                       CASE
                           WHEN resolved.inventory_metadata ->> 'mirror_downloaded' = 'true'
                               THEN 'maitu_mirror'
                           ELSE 'asset_materials'
                       END AS source_root_kind
                FROM resolved
                LEFT JOIN assets AS asset
                  ON asset.asset_code = resolved.asset_code AND asset.deleted_at IS NULL
                WHERE resolved.asset_code IS NOT NULL
                  AND (
                      asset.asset_type = 'VID'
                      OR lower(COALESCE(resolved.material_type, '')) IN
                         ('video', 'decorative_video', 'product_video')
                  )
                ORDER BY resolved.asset_code, resolved.requirement_code
                """,
                (run_code, run["inventory_snapshot_id"]),
            )
            selected = cursor.fetchall()
            for item in selected:
                analysis_code = self._next_code(cursor, "MT-MAT-AN", "MAITU_MATERIAL_ANALYSIS")
                identity_ready = bool(item.get("asset_fingerprint") and item.get("source_relative_path"))
                cursor.execute(
                    """
                    INSERT INTO maitu_workbench_video_analyses (
                        analysis_code, run_id, run_code, origin_requirement_id,
                        requirement_code, asset_code, asset_fingerprint, asset_title,
                        source_relative_path, source_root_kind, status,
                        error_code, error_message, completed_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id, asset_code) DO NOTHING
                    """,
                    (
                        analysis_code,
                        run["id"],
                        run_code,
                        item["requirement_id"],
                        item["requirement_code"],
                        item["asset_code"],
                        item.get("asset_fingerprint"),
                        item["asset_title"],
                        item.get("source_relative_path"),
                        item.get("source_root_kind"),
                        "queued" if identity_ready else "failed",
                        None if identity_ready else "MATERIAL_SOURCE_UNAVAILABLE",
                        None if identity_ready else "Selected video has no immutable fingerprint or local source",
                        None if identity_ready else datetime.now(UTC),
                    ),
                )
        self.connection.commit()
        return self.list_video_analyses(run_code)

    def synchronize_all_selected_video_analyses(self) -> int:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT run_code FROM maitu_workbench_runs
                WHERE active_plan_revision > 0
                  AND status NOT IN ('completed', 'failed')
                ORDER BY created_at
                """
            )
            run_codes = [str(row["run_code"]) for row in cursor.fetchall()]
        before = 0
        for run_code in run_codes:
            rows = self.synchronize_selected_video_analyses(run_code)
            before += len(rows or [])
        return before

    def selected_video_asset_codes(self, run_code: str) -> set[str] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT id FROM maitu_workbench_runs WHERE run_code = %s", (run_code,))
            run = cursor.fetchone()
            if run is None:
                return None
            cursor.execute(
                """
                SELECT DISTINCT COALESCE(decision.selected_asset_code, item.asset_code) AS asset_code
                FROM maitu_workbench_material_requirements AS req
                JOIN maitu_workbench_runs AS active_run ON active_run.id = req.run_id
                JOIN LATERAL (
                    SELECT material_decision.*
                    FROM maitu_workbench_material_decisions AS material_decision
                    WHERE material_decision.requirement_id = req.id
                    ORDER BY material_decision.revision_number DESC
                    LIMIT 1
                ) AS decision ON decision.decision = 'selected'
                LEFT JOIN maitu_workbench_inventory_snapshot_items AS item
                  ON item.snapshot_id = active_run.inventory_snapshot_id
                 AND item.item_key = decision.selected_material_key
                WHERE active_run.run_code = %s
                  AND req.plan_revision_number = active_run.active_plan_revision
                  AND req.status = 'selected'
                """,
                (run_code,),
            )
            return {str(row["asset_code"]) for row in cursor.fetchall() if row.get("asset_code")}

    def list_video_analyses(self, run_code: str) -> list[dict[str, Any]] | None:
        selected = self.selected_video_asset_codes(run_code)
        if selected is None:
            return None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT analysis.*,
                       (
                           SELECT count(*)
                           FROM maitu_workbench_analysis_conflicts AS conflict
                           WHERE conflict.analysis_id = analysis.id AND conflict.is_current = true
                       ) AS conflict_count
                FROM maitu_workbench_video_analyses AS analysis
                WHERE analysis.run_code = %s
                ORDER BY analysis.created_at, analysis.analysis_code
                """,
                (run_code,),
            )
            rows = cursor.fetchall()
        result = []
        for row in rows:
            item = self._serialize(row)
            item["selected"] = str(row["asset_code"]) in selected
            result.append(item)
        return result

    def get_video_analysis(self, analysis_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT analysis.*,
                       (
                           SELECT count(*) FROM maitu_workbench_analysis_conflicts AS conflict
                           WHERE conflict.analysis_id = analysis.id AND conflict.is_current = true
                       ) AS conflict_count
                FROM maitu_workbench_video_analyses AS analysis
                WHERE analysis.analysis_code = %s
                """,
                (analysis_code,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        selected = self.selected_video_asset_codes(str(row["run_code"])) or set()
        result = self._serialize(row)
        result["selected"] = str(row["asset_code"]) in selected
        return result

    def claim_video_analysis(
        self,
        worker_id: str,
        lease_seconds: int,
        *,
        analysis_code: str | None = None,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE maitu_workbench_video_analyses
                SET status = 'queued', attempt = attempt + 1, claimed_by = NULL,
                    lease_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
                    started_at = NULL, updated_at = now()
                WHERE status = 'running' AND lease_expires_at <= now()
                """
            )
            code_clause = "AND analysis_code = %s" if analysis_code else ""
            params: list[Any] = []
            if analysis_code:
                params.append(analysis_code)
            cursor.execute(
                f"""
                SELECT * FROM maitu_workbench_video_analyses
                WHERE status = 'queued' {code_clause}
                ORDER BY created_at, analysis_code
                FOR UPDATE SKIP LOCKED LIMIT 1
                """,
                tuple(params),
            )
            candidate = cursor.fetchone()
            if candidate is None:
                self.connection.commit()
                return None
            cursor.execute(
                """
                UPDATE maitu_workbench_video_analyses
                SET status = 'running', claimed_by = %s, lease_token = gen_random_uuid(),
                    lease_expires_at = now() + make_interval(secs => %s),
                    heartbeat_at = now(), started_at = COALESCE(started_at, now()),
                    error_code = NULL, error_message = NULL, completed_at = NULL, updated_at = now()
                WHERE id = %s RETURNING *
                """,
                (worker_id, lease_seconds, candidate["id"]),
            )
            claimed = cursor.fetchone()
        self.connection.commit()
        result = self._serialize(claimed)
        result["selected"] = True
        result["conflict_count"] = 0
        return result

    def heartbeat_video_analysis(
        self,
        analysis_code: str,
        worker_id: str,
        lease_token: str,
        lease_seconds: int,
    ) -> dict[str, Any] | None:
        token = self._parse_uuid(lease_token)
        if token is None:
            return None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE maitu_workbench_video_analyses
                SET lease_expires_at = now() + make_interval(secs => %s),
                    heartbeat_at = now(), updated_at = now()
                WHERE analysis_code = %s AND status = 'running' AND claimed_by = %s
                  AND lease_token = %s AND lease_expires_at > now()
                RETURNING *
                """,
                (lease_seconds, analysis_code, worker_id, token),
            )
            row = cursor.fetchone()
        self.connection.commit()
        if row is None:
            return None
        result = self._serialize(row)
        result.update(selected=True, conflict_count=0)
        return result

    def complete_video_analysis(
        self,
        analysis_code: str,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        legacy_contract = payload.get("analysis_strategy_revision") is None
        strategy_revision = (
            "legacy.material-vision.v1"
            if legacy_contract
            else str(payload["analysis_strategy_revision"])
        )
        if legacy_contract:
            analysis_prompt_revision = payload.get("model_prompt_version")
            analysis_input_fingerprint = payload.get("model_input_fingerprint")
            analysis_output_fingerprint = payload.get("model_output_fingerprint")
            model_provider = payload.get("model_provider")
            model_requested = payload.get("model_requested")
            model_actual = payload.get("model_actual")
            model_prompt_version = payload.get("model_prompt_version")
            model_request_id = payload.get("model_request_id")
            model_input_fingerprint = payload.get("model_input_fingerprint")
            model_output_fingerprint = payload.get("model_output_fingerprint")
            model_usage = payload.get("model_usage") or {}
            model_latency_ms = payload.get("model_latency_ms")
        else:
            analysis_prompt_revision = payload["analysis_prompt_revision"]
            analysis_input_fingerprint = payload["analysis_input_fingerprint"]
            analysis_output_fingerprint = payload["analysis_output_fingerprint"]
            model_provider = None
            model_requested = None
            model_actual = None
            model_prompt_version = None
            model_request_id = None
            model_input_fingerprint = None
            model_output_fingerprint = None
            model_usage = {}
            model_latency_ms = None
        token = self._parse_uuid(lease_token)
        if token is None:
            raise MaituWorkbenchLeaseConflictError("Video analysis lease is invalid")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_owned_job(
                cursor,
                table="maitu_workbench_video_analyses",
                code_column="analysis_code",
                code=analysis_code,
                worker_id=worker_id,
                lease_token=token,
            )
            if job is None:
                self.connection.rollback()
                raise MaituWorkbenchLeaseConflictError("Video analysis lease is not active")
            cursor.execute(
                """
                UPDATE maitu_workbench_video_analyses
                SET status = 'succeeded', provisional_source = 'strategy_frames',
                    provisional_summary = %s, technical = %s, frame_manifest = %s,
                    automatic_observation = %s, merged_profile = %s,
                    analysis_strategy_revision = %s, invocation_evidence_ref = %s,
                    analysis_prompt_revision = %s, analysis_input_fingerprint = %s,
                    analysis_output_fingerprint = %s,
                    model_provider = %s, model_requested = %s, model_actual = %s,
                    model_prompt_version = %s, model_request_id = %s,
                    model_input_fingerprint = %s, model_output_fingerprint = %s,
                    model_usage = %s, model_latency_ms = %s,
                    claimed_by = NULL, lease_token = NULL, lease_expires_at = NULL,
                    heartbeat_at = NULL, error_code = NULL, error_message = NULL,
                    completed_at = now(), updated_at = now()
                WHERE id = %s RETURNING *
                """,
                (
                    payload["observation"]["summary"],
                    Jsonb(payload["technical"]),
                    Jsonb(payload["frame_manifest"]),
                    Jsonb(payload["observation"]),
                    Jsonb(payload["merged_profile"]),
                    strategy_revision,
                    payload.get("invocation_evidence_ref"),
                    analysis_prompt_revision,
                    analysis_input_fingerprint,
                    analysis_output_fingerprint,
                    model_provider,
                    model_requested,
                    model_actual,
                    model_prompt_version,
                    model_request_id,
                    model_input_fingerprint,
                    model_output_fingerprint,
                    Jsonb(model_usage),
                    model_latency_ms,
                    job["id"],
                ),
            )
            completed = cursor.fetchone()
        self.connection.commit()
        result = self._serialize(completed)
        result.update(selected=True, conflict_count=0)
        return result

    def fail_video_analysis(
        self,
        analysis_code: str,
        worker_id: str,
        lease_token: str,
        *,
        error_code: str,
        error_message: str,
    ) -> dict[str, Any]:
        token = self._parse_uuid(lease_token)
        if token is None:
            raise MaituWorkbenchLeaseConflictError("Video analysis lease is invalid")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_owned_job(
                cursor,
                table="maitu_workbench_video_analyses",
                code_column="analysis_code",
                code=analysis_code,
                worker_id=worker_id,
                lease_token=token,
            )
            if job is None:
                self.connection.rollback()
                raise MaituWorkbenchLeaseConflictError("Video analysis lease is not active")
            cursor.execute(
                """
                UPDATE maitu_workbench_video_analyses
                SET status = 'failed', claimed_by = NULL, lease_token = NULL,
                    lease_expires_at = NULL, heartbeat_at = NULL,
                    error_code = %s, error_message = %s,
                    completed_at = now(), updated_at = now()
                WHERE id = %s RETURNING *
                """,
                (error_code, error_message, job["id"]),
            )
            failed = cursor.fetchone()
        self.connection.commit()
        result = self._serialize(failed)
        result.update(selected=True, conflict_count=0)
        return result

    def retry_video_analysis(self, analysis_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE maitu_workbench_video_analyses
                SET status = 'queued', attempt = attempt + 1,
                    provisional_source = 'none', provisional_summary = NULL,
                    claimed_by = NULL, lease_token = NULL, lease_expires_at = NULL,
                    heartbeat_at = NULL, error_code = NULL, error_message = NULL,
                    started_at = NULL, completed_at = NULL, updated_at = now()
                WHERE analysis_code = %s AND status = 'failed'
                  AND asset_fingerprint IS NOT NULL AND source_relative_path IS NOT NULL
                RETURNING *
                """,
                (analysis_code,),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    "SELECT status FROM maitu_workbench_video_analyses WHERE analysis_code = %s",
                    (analysis_code,),
                )
                existing = cursor.fetchone()
                self.connection.rollback()
                if existing is None:
                    return None
                raise MaituWorkbenchConflictError(
                    "Only failed video analyses with an immutable local source can be retried"
                )
        self.connection.commit()
        result = self._serialize(row)
        result.update(selected=True, conflict_count=0)
        return result

    def persist_gemini_submission(
        self,
        run_code: str,
        analysis_code: str,
        *,
        raw_submission: dict[str, Any],
        parsed_observation: dict[str, Any],
        merged_profile: dict[str, Any],
        submitted_by: str | None,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM maitu_workbench_video_analyses
                WHERE run_code = %s AND analysis_code = %s FOR UPDATE
                """,
                (run_code, analysis_code),
            )
            analysis = cursor.fetchone()
            if analysis is None:
                self.connection.rollback()
                return None
            if analysis["status"] != "succeeded" or not analysis.get("automatic_observation"):
                self.connection.rollback()
                raise MaituWorkbenchConflictError(
                    "Secondary manual backfill requires a completed provisional strategy analysis"
                )
            revision = int(analysis["current_gemini_revision"]) + 1
            submission_code = self._next_code(cursor, "MT-GEM-SUB", "MAITU_GEMINI_SUBMISSION")
            cursor.execute(
                """
                INSERT INTO maitu_workbench_gemini_submissions (
                    submission_code, analysis_id, analysis_code, run_id, run_code,
                    revision_number, asset_code, asset_fingerprint, prompt_schema_version,
                    raw_submission, parsed_observation, merged_profile, submitted_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                        'gemini-material-analysis-v1', %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    submission_code,
                    analysis["id"],
                    analysis_code,
                    analysis["run_id"],
                    run_code,
                    revision,
                    analysis["asset_code"],
                    analysis["asset_fingerprint"],
                    Jsonb(raw_submission),
                    Jsonb(parsed_observation),
                    Jsonb(merged_profile),
                    submitted_by,
                ),
            )
            submission = cursor.fetchone()
            cursor.execute(
                """
                UPDATE maitu_workbench_analysis_conflicts
                SET is_current = false, superseded_at = now()
                WHERE analysis_id = %s AND is_current = true
                """,
                (analysis["id"],),
            )
            conflicts = list(merged_profile.get("conflicts") or [])
            for conflict in conflicts:
                conflict_code = self._next_code(cursor, "MT-MAT-CON", "MAITU_MATERIAL_CONFLICT")
                cursor.execute(
                    """
                    INSERT INTO maitu_workbench_analysis_conflicts (
                        conflict_code, analysis_id, analysis_code, submission_id,
                        submission_code, run_id, run_code, field, severity,
                        provisional_value, gemini_value, reason
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        conflict_code,
                        analysis["id"],
                        analysis_code,
                        submission["id"],
                        submission_code,
                        analysis["run_id"],
                        run_code,
                        conflict["field"],
                        conflict["severity"],
                        Jsonb(conflict.get("automatic_value")),
                        Jsonb(conflict.get("manual_value")),
                        conflict["reason"],
                    ),
                )
            summary = str(parsed_observation.get("summary") or "")
            cursor.execute(
                """
                UPDATE maitu_workbench_video_analyses
                SET gemini_status = 'succeeded', gemini_summary = %s,
                    current_gemini_revision = %s, merged_profile = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (summary, revision, Jsonb(merged_profile), analysis["id"]),
            )
        self.connection.commit()
        return self.get_video_analysis(analysis_code)

    def list_analysis_conflicts(
        self,
        run_code: str,
        *,
        selected_only: bool = True,
    ) -> list[dict[str, Any]] | None:
        selected = self.selected_video_asset_codes(run_code)
        if selected is None:
            return None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT conflict.*, analysis.asset_code
                FROM maitu_workbench_analysis_conflicts AS conflict
                JOIN maitu_workbench_video_analyses AS analysis ON analysis.id = conflict.analysis_id
                WHERE conflict.run_code = %s AND conflict.is_current = true
                ORDER BY conflict.created_at, conflict.conflict_code
                """,
                (run_code,),
            )
            rows = cursor.fetchall()
        result = []
        for row in rows:
            if selected_only and str(row["asset_code"]) not in selected:
                continue
            item = self._serialize(row)
            item["provisional_value"] = self._format_conflict_value(item.get("provisional_value"))
            item["gemini_value"] = self._format_conflict_value(item.get("gemini_value"))
            result.append(item)
        return result

    def resolve_analysis_conflict(
        self,
        run_code: str,
        conflict_code: str,
        *,
        resolution: str,
        resolved_by: str,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM maitu_workbench_analysis_conflicts
                WHERE run_code = %s AND conflict_code = %s AND is_current = true
                FOR UPDATE
                """,
                (run_code, conflict_code),
            )
            conflict = cursor.fetchone()
            if conflict is None:
                self.connection.rollback()
                return None
            if conflict.get("resolution"):
                self.connection.rollback()
                if conflict["resolution"] != resolution:
                    raise MaituWorkbenchConflictError("An analysis conflict decision is immutable")
                result = self._serialize(conflict)
            else:
                cursor.execute(
                    """
                    UPDATE maitu_workbench_analysis_conflicts
                    SET resolution = %s, resolved_by = %s, resolved_at = now()
                    WHERE id = %s RETURNING *
                    """,
                    (resolution, resolved_by, conflict["id"]),
                )
                result = self._serialize(cursor.fetchone())
                self.connection.commit()
        result["provisional_value"] = self._format_conflict_value(result.get("provisional_value"))
        result["gemini_value"] = self._format_conflict_value(result.get("gemini_value"))
        return result

    def list_selected_analysis_blockers(self, run_code: str) -> list[dict[str, Any]]:
        selected = self.selected_video_asset_codes(run_code)
        if not selected:
            return []
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT conflict.conflict_code, conflict.analysis_code, analysis.asset_code,
                       conflict.field, conflict.severity, conflict.resolution
                FROM maitu_workbench_analysis_conflicts AS conflict
                JOIN maitu_workbench_video_analyses AS analysis ON analysis.id = conflict.analysis_id
                WHERE conflict.run_code = %s AND conflict.is_current = true
                  AND (
                      (conflict.severity = 'critical' AND conflict.resolution IS NULL)
                      OR conflict.resolution = 'replace_asset'
                  )
                ORDER BY conflict.created_at, conflict.conflict_code
                """,
                (run_code,),
            )
            rows = cursor.fetchall()
        return [self._serialize(row) for row in rows if str(row["asset_code"]) in selected]

    # Helpers -----------------------------------------------------------

    @staticmethod
    def _find_product_id(cursor: Any, product_code: str | None) -> UUID | None:
        if not product_code:
            return None
        cursor.execute(
            "SELECT id FROM products WHERE product_code = %s AND deleted_at IS NULL",
            (product_code,),
        )
        row = cursor.fetchone()
        return row["id"] if row else None

    @staticmethod
    def _next_code(cursor: Any, prefix: str, object_type: str) -> str:
        sequence_date = datetime.now(UTC).date()
        cursor.execute(
            """
            INSERT INTO business_sequences (sequence_date, object_type, current_value)
            VALUES (%s, %s, 1)
            ON CONFLICT (sequence_date, object_type)
            DO UPDATE SET current_value = business_sequences.current_value + 1, updated_at = now()
            RETURNING current_value
            """,
            (sequence_date, object_type),
        )
        sequence = int(cursor.fetchone()["current_value"])
        return f"{prefix}-{sequence_date:%Y%m%d}-{sequence:06d}"

    @staticmethod
    def _lock_owned_job(
        cursor: Any,
        *,
        table: str,
        code_column: str,
        code: str,
        worker_id: str,
        lease_token: UUID,
    ) -> dict[str, Any] | None:
        allowed = {
            ("maitu_workbench_inventory_sync_jobs", "sync_job_code"),
            ("maitu_workbench_draft_execution_jobs", "execution_job_code"),
            ("maitu_workbench_video_analyses", "analysis_code"),
        }
        if (table, code_column) not in allowed:
            raise ValueError("unsupported lease table")
        cursor.execute(
            f"""
            SELECT * FROM {table}
            WHERE {code_column} = %s AND status = 'running' AND claimed_by = %s
              AND lease_token = %s AND lease_expires_at > now()
            FOR UPDATE
            """,
            (code, worker_id, lease_token),
        )
        return cursor.fetchone()

    @staticmethod
    def _parse_uuid(value: str) -> UUID | None:
        try:
            return UUID(str(value))
        except (TypeError, ValueError, AttributeError):
            return None

    @staticmethod
    def _format_conflict_value(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        import json

        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _serialize(cls, value: Any) -> Any:
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, dict):
            return {key: cls._serialize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._serialize(item) for item in value]
        if isinstance(value, tuple):
            return [cls._serialize(item) for item in value]
        return value
