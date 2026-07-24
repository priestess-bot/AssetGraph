from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row


class MaterialLibraryNotFoundError(RuntimeError):
    pass


class MaterialLibraryValidationError(RuntimeError):
    pass


class MaterialLibraryRepository:
    def __init__(self, connection: Connection):
        self.connection = connection

    def update_asset_classification(
        self,
        asset_code: str,
        *,
        media_kind: str | None,
        material_roles: list[str],
        execution_capability: str,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE assets
                SET media_kind = %s, material_roles = %s::jsonb,
                    execution_capability = %s, updated_at = now()
                WHERE asset_code = %s AND deleted_at IS NULL
                RETURNING *
                """,
                (media_kind, json.dumps(sorted(set(material_roles))), execution_capability, asset_code),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._stringify(row) if row else None

    def create_group(self, payload: dict[str, Any]) -> dict[str, Any]:
        codes = self._dedupe_codes(payload.get("asset_codes") or [])
        with self.connection.cursor(row_factory=dict_row) as cursor:
            self._require_assets(cursor, codes)
            group_code = self._next_code(cursor, "AG-GRP", "asset_group")
            cursor.execute(
                """INSERT INTO asset_groups (group_code, title, description)
                   VALUES (%s, %s, %s) RETURNING *""",
                (group_code, payload["title"], payload.get("description")),
            )
            row = cursor.fetchone()
            self._replace_group_members(cursor, row["id"], codes)
        self.connection.commit()
        return self.get_group(group_code)  # type: ignore[return-value]

    def list_groups(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT g.*, COALESCE(array_agg(a.asset_code ORDER BY a.asset_code)
                    FILTER (WHERE a.asset_code IS NOT NULL), '{}') AS asset_codes
                FROM asset_groups g
                LEFT JOIN asset_group_members gm ON gm.group_id = g.id
                LEFT JOIN assets a ON a.id = gm.asset_id AND a.deleted_at IS NULL
                GROUP BY g.id ORDER BY g.updated_at DESC, g.group_code
                """
            )
            rows = cursor.fetchall()
        return [self._group_read(row) for row in rows]

    def get_group(self, group_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT g.*, COALESCE(array_agg(a.asset_code ORDER BY a.asset_code)
                    FILTER (WHERE a.asset_code IS NOT NULL), '{}') AS asset_codes
                FROM asset_groups g
                LEFT JOIN asset_group_members gm ON gm.group_id = g.id
                LEFT JOIN assets a ON a.id = gm.asset_id AND a.deleted_at IS NULL
                WHERE g.group_code = %s GROUP BY g.id
                """,
                (group_code,),
            )
            row = cursor.fetchone()
        return self._group_read(row) if row else None

    def replace_group_members(self, group_code: str, asset_codes: list[str]) -> dict[str, Any] | None:
        codes = self._dedupe_codes(asset_codes)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT id FROM asset_groups WHERE group_code = %s FOR UPDATE", (group_code,))
            group = cursor.fetchone()
            if group is None:
                self.connection.rollback()
                return None
            self._require_assets(cursor, codes)
            self._replace_group_members(cursor, group["id"], codes)
            cursor.execute("UPDATE asset_groups SET updated_at = now() WHERE id = %s", (group["id"],))
        self.connection.commit()
        return self.get_group(group_code)

    def write_constraint_profile(self, asset_code: str, constraints: list[dict[str, Any]]) -> dict[str, Any] | None:
        canonical = self._canonical(constraints)
        fingerprint = self._fingerprint(canonical)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT id FROM assets WHERE asset_code = %s AND deleted_at IS NULL", (asset_code,))
            asset = cursor.fetchone()
            if asset is None:
                self.connection.rollback()
                return None
            cursor.execute("SELECT * FROM asset_constraint_profiles WHERE asset_id = %s FOR UPDATE", (asset["id"],))
            profile = cursor.fetchone()
            if profile is None:
                profile_code = self._next_code(cursor, "AG-CP", "asset_constraint_profile")
                cursor.execute(
                    """INSERT INTO asset_constraint_profiles (profile_code, asset_id, asset_code, current_revision)
                       VALUES (%s, %s, %s, 0) RETURNING *""",
                    (profile_code, asset["id"], asset_code),
                )
                profile = cursor.fetchone()
            revision = int(profile["current_revision"]) + 1
            cursor.execute(
                """INSERT INTO asset_constraint_profile_revisions
                   (profile_id, revision_number, constraints, fingerprint_sha256)
                   VALUES (%s, %s, %s::jsonb, %s)""",
                (profile["id"], revision, canonical, fingerprint),
            )
            cursor.execute(
                "UPDATE asset_constraint_profiles SET current_revision = %s, updated_at = now() WHERE id = %s",
                (revision, profile["id"]),
            )
        self.connection.commit()
        return self.get_constraint_profile(asset_code)

    def get_constraint_profile(self, asset_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT p.profile_code, p.asset_code, r.revision_number, r.constraints,
                       r.fingerprint_sha256, r.created_at
                FROM asset_constraint_profiles p
                JOIN asset_constraint_profile_revisions r
                  ON r.profile_id = p.id AND r.revision_number = p.current_revision
                WHERE p.asset_code = %s
                """,
                (asset_code,),
            )
            row = cursor.fetchone()
        return self._stringify(row) if row else None

    def create_pack(self, payload: dict[str, Any]) -> dict[str, Any]:
        entries = payload.get("entries") or []
        self._validate_pack_entries(entries)
        canonical = self._canonical(entries)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            self._require_entry_targets(cursor, entries)
            pack_code = self._next_code(cursor, "AG-PACK", "material_pack")
            cursor.execute(
                """INSERT INTO material_packs (pack_code, title, role, description, current_revision)
                   VALUES (%s, %s, %s, %s, 1) RETURNING *""",
                (pack_code, payload["title"], payload["role"], payload.get("description")),
            )
            pack = cursor.fetchone()
            cursor.execute(
                """INSERT INTO material_pack_revisions (pack_id, revision_number, entries, fingerprint_sha256)
                   VALUES (%s, 1, %s::jsonb, %s)""",
                (pack["id"], canonical, self._fingerprint(canonical)),
            )
        self.connection.commit()
        return self.get_pack(pack_code)  # type: ignore[return-value]

    def list_packs(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT p.pack_code, p.title, p.role, p.description, p.current_revision,
                       p.status, p.created_at, p.updated_at, r.entries, r.fingerprint_sha256
                FROM material_packs p
                JOIN material_pack_revisions r ON r.pack_id = p.id AND r.revision_number = p.current_revision
                WHERE p.status <> 'archived' ORDER BY p.updated_at DESC, p.pack_code
                """
            )
            rows = cursor.fetchall()
        return [self._pack_read(row) for row in rows]

    def get_pack(self, pack_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT p.pack_code, p.title, p.role, p.description, p.current_revision,
                       p.status, p.created_at, p.updated_at, r.entries, r.fingerprint_sha256
                FROM material_packs p
                JOIN material_pack_revisions r ON r.pack_id = p.id AND r.revision_number = p.current_revision
                WHERE p.pack_code = %s
                """,
                (pack_code,),
            )
            row = cursor.fetchone()
        return self._pack_read(row) if row else None

    def publish_pack(self, pack_code: str) -> dict[str, Any] | None:
        """Make the current immutable pack revision eligible for branch selection."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT id, status FROM material_packs WHERE pack_code = %s FOR UPDATE", (pack_code,))
            pack = cursor.fetchone()
            if pack is None:
                self.connection.rollback()
                return None
            if pack["status"] == "archived":
                self.connection.rollback()
                raise MaterialLibraryValidationError("Archived material packs cannot be published")
            if pack["status"] != "published":
                cursor.execute(
                    "UPDATE material_packs SET status = 'published', updated_at = now() WHERE id = %s",
                    (pack["id"],),
                )
        self.connection.commit()
        return self.get_pack(pack_code)

    def resolve_published_packs(self, pack_codes: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        """Expand pack/group membership once so a downstream snapshot has no dynamic references."""
        refs: list[dict[str, Any]] = []
        resolved_codes: list[str] = []
        for pack_code in self._dedupe_codes(pack_codes):
            pack = self.get_pack(pack_code)
            if pack is None:
                raise MaterialLibraryValidationError(f"Unknown material pack code: {pack_code}")
            if pack["status"] != "published":
                raise MaterialLibraryValidationError(f"Material pack must be published before selection: {pack_code}")
            asset_codes = list(pack["resolved_asset_codes"])
            if not asset_codes:
                raise MaterialLibraryValidationError(f"Published material pack resolves to no active assets: {pack_code}")
            refs.append(
                {
                    "pack_code": pack["pack_code"],
                    "revision_number": int(pack["revision_number"]),
                    "fingerprint_sha256": pack["fingerprint_sha256"],
                    "role": pack["role"],
                    "entries": pack["entries"],
                    "resolved_asset_codes": asset_codes,
                }
            )
            resolved_codes.extend(asset_codes)
        return refs, self._dedupe_codes(resolved_codes)

    def create_gap(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            code = self._next_code(cursor, "AG-GAP", "asset_gap")
            cursor.execute(
                """INSERT INTO asset_gaps
                   (gap_code, title, role, severity, specification, source_context)
                   VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb) RETURNING *""",
                (
                    code,
                    payload["title"],
                    payload["role"],
                    payload.get("severity", "medium"),
                    json.dumps(payload.get("specification") or {}),
                    json.dumps(payload.get("source_context") or {}),
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._stringify(row)

    def list_gaps(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM asset_gaps ORDER BY updated_at DESC, gap_code")
            rows = cursor.fetchall()
        return [self._stringify(row) for row in rows]

    def update_gap(self, gap_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """UPDATE asset_gaps SET status = %s, resolution_asset_code = %s, updated_at = now()
                   WHERE gap_code = %s RETURNING *""",
                (payload["status"], payload.get("resolution_asset_code"), gap_code),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._stringify(row) if row else None

    @staticmethod
    def _canonical(value: Any) -> str:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _fingerprint(cls, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _dedupe_codes(values: list[str]) -> list[str]:
        return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))

    def _require_assets(self, cursor: Any, codes: list[str]) -> None:
        if not codes:
            return
        cursor.execute("SELECT asset_code FROM assets WHERE asset_code = ANY(%s) AND deleted_at IS NULL", (codes,))
        found = {row["asset_code"] for row in cursor.fetchall()}
        missing = sorted(set(codes) - found)
        if missing:
            raise MaterialLibraryValidationError(f"Unknown active asset codes: {', '.join(missing)}")

    def _replace_group_members(self, cursor: Any, group_id: Any, codes: list[str]) -> None:
        cursor.execute("DELETE FROM asset_group_members WHERE group_id = %s", (group_id,))
        if not codes:
            return
        cursor.execute("SELECT id, asset_code FROM assets WHERE asset_code = ANY(%s) AND deleted_at IS NULL", (codes,))
        by_code = {row["asset_code"]: row["id"] for row in cursor.fetchall()}
        cursor.executemany(
            "INSERT INTO asset_group_members (group_id, asset_id) VALUES (%s, %s)",
            [(group_id, by_code[code]) for code in codes],
        )

    def _require_entry_targets(self, cursor: Any, entries: list[dict[str, Any]]) -> None:
        asset_codes = [entry["selection_code"] for entry in entries if entry["selection_kind"] == "asset"]
        group_codes = [entry["selection_code"] for entry in entries if entry["selection_kind"] == "group"]
        self._require_assets(cursor, self._dedupe_codes(asset_codes))
        if group_codes:
            cursor.execute("SELECT group_code FROM asset_groups WHERE group_code = ANY(%s)", (self._dedupe_codes(group_codes),))
            found = {row["group_code"] for row in cursor.fetchall()}
            missing = sorted(set(group_codes) - found)
            if missing:
                raise MaterialLibraryValidationError(f"Unknown asset group codes: {', '.join(missing)}")

    @staticmethod
    def _validate_pack_entries(entries: list[dict[str, Any]]) -> None:
        if not entries:
            raise MaterialLibraryValidationError("Material pack must contain at least one entry")

    def _resolve_entries(self, entries: list[dict[str, Any]]) -> list[str]:
        direct = [entry["selection_code"] for entry in entries if entry["selection_kind"] == "asset"]
        group_codes = [entry["selection_code"] for entry in entries if entry["selection_kind"] == "group"]
        resolved = list(direct)
        if group_codes:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """SELECT DISTINCT a.asset_code FROM asset_group_members gm
                       JOIN asset_groups g ON g.id = gm.group_id
                       JOIN assets a ON a.id = gm.asset_id AND a.deleted_at IS NULL
                       WHERE g.group_code = ANY(%s) ORDER BY a.asset_code""",
                    (group_codes,),
                )
                resolved.extend(row["asset_code"] for row in cursor.fetchall())
        return self._dedupe_codes(resolved)

    def _group_read(self, row: dict[str, Any]) -> dict[str, Any]:
        result = self._stringify(row)
        result["asset_codes"] = list(result.get("asset_codes") or [])
        result["asset_count"] = len(result["asset_codes"])
        return result

    def _pack_read(self, row: dict[str, Any]) -> dict[str, Any]:
        result = self._stringify(row)
        result["revision_number"] = result.pop("current_revision")
        result["resolved_asset_codes"] = self._resolve_entries(result.get("entries") or [])
        return result

    @staticmethod
    def _stringify(row: dict[str, Any] | None) -> dict[str, Any]:
        if row is None:
            return {}
        return {key: str(value) if key == "id" and value is not None else value for key, value in row.items()}

    @staticmethod
    def _next_code(cursor: Any, prefix: str, object_type: str) -> str:
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
        sequence = int(cursor.fetchone()["current_value"])
        return f"{prefix}-{sequence_date:%Y%m%d}-{sequence:06d}"
