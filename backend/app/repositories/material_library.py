from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from math import isfinite
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row


class MaterialLibraryNotFoundError(RuntimeError):
    pass


class MaterialLibraryValidationError(RuntimeError):
    pass


class MaterialLibraryConflictError(RuntimeError):
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

    def update_asset_classifications(
        self,
        asset_codes: list[str],
        *,
        media_kind: str | None,
        material_roles: list[str],
        execution_capability: str,
    ) -> list[dict[str, Any]]:
        """Apply one explicit three-axis classification to an all-or-nothing target set."""
        codes = self._dedupe_codes(asset_codes)
        if not codes:
            raise MaterialLibraryValidationError("At least one asset code is required")
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """SELECT asset_code FROM assets
                       WHERE asset_code = ANY(%s) AND deleted_at IS NULL FOR UPDATE""",
                    (codes,),
                )
                found = {row["asset_code"] for row in cursor.fetchall()}
                missing = sorted(set(codes) - found)
                if missing:
                    raise MaterialLibraryValidationError(
                        f"Unknown active asset codes: {', '.join(missing)}"
                    )
                cursor.execute(
                    """UPDATE assets
                       SET media_kind = %s, material_roles = %s::jsonb,
                           execution_capability = %s, updated_at = now()
                       WHERE asset_code = ANY(%s) AND deleted_at IS NULL
                       RETURNING *""",
                    (
                        media_kind,
                        json.dumps(sorted(set(material_roles))),
                        execution_capability,
                        codes,
                    ),
                )
                by_code = {row["asset_code"]: self._stringify(row) for row in cursor.fetchall()}
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return [by_code[code] for code in codes]

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
                       r.fingerprint_sha256, r.created_at, r.created_by, r.change_reason,
                       r.source_plan_code, r.source_profile_revision, r.source_room_override
                FROM asset_constraint_profiles p
                JOIN asset_constraint_profile_revisions r
                  ON r.profile_id = p.id AND r.revision_number = p.current_revision
                WHERE p.asset_code = %s
                """,
                (asset_code,),
            )
            row = cursor.fetchone()
        return self._stringify(row) if row else None

    def list_constraint_profile_revisions(self, asset_code: str) -> list[dict[str, Any]]:
        """Read immutable constraint revisions without treating the latest row as mutable."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT p.profile_code, p.asset_code, r.revision_number, r.constraints,
                       r.fingerprint_sha256, r.created_at, r.created_by, r.change_reason,
                       r.source_plan_code, r.source_profile_revision, r.source_room_override
                FROM asset_constraint_profiles p
                JOIN asset_constraint_profile_revisions r ON r.profile_id = p.id
                WHERE p.asset_code = %s
                ORDER BY r.revision_number DESC
                """,
                (asset_code,),
            )
            rows = cursor.fetchall()
        return [self._stringify(row) for row in rows]

    def promote_room_constraint_override(
        self,
        asset_code: str,
        *,
        plan_code: str,
        expected_revision: int,
        actor: str,
        reason: str,
    ) -> dict[str, Any] | None:
        """Promote persisted room geometry to one auditable global Profile revision."""
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT build_plan FROM functional_live_room_plans WHERE plan_code = %s FOR UPDATE",
                    (plan_code,),
                )
                plan = cursor.fetchone()
                if plan is None:
                    raise MaterialLibraryNotFoundError("Live-room plan not found")
                inventory = dict((plan["build_plan"] or {}).get("inventory_snapshot") or {})
                override = dict((inventory.get("room_constraint_overrides") or {}).get(asset_code) or {})
                geometry = self._normalized_override_geometry(override)

                cursor.execute(
                    "SELECT id FROM assets WHERE asset_code = %s AND deleted_at IS NULL FOR UPDATE",
                    (asset_code,),
                )
                asset = cursor.fetchone()
                if asset is None:
                    self.connection.rollback()
                    return None
                cursor.execute(
                    "SELECT * FROM asset_constraint_profiles WHERE asset_id = %s FOR UPDATE",
                    (asset["id"],),
                )
                profile = cursor.fetchone()
                if profile is None:
                    if expected_revision != 0:
                        raise MaterialLibraryConflictError(
                            "CONSTRAINT_PROFILE_REVISION_CONFLICT: profile does not exist"
                        )
                    profile_code = self._next_code(cursor, "AG-CP", "asset_constraint_profile")
                    cursor.execute(
                        """INSERT INTO asset_constraint_profiles
                           (profile_code, asset_id, asset_code, current_revision)
                           VALUES (%s, %s, %s, 0) RETURNING *""",
                        (profile_code, asset["id"], asset_code),
                    )
                    profile = cursor.fetchone()
                cursor.execute(
                    """SELECT r.revision_number, r.constraints, r.fingerprint_sha256, r.created_at,
                              r.created_by, r.change_reason, r.source_plan_code,
                              r.source_profile_revision, r.source_room_override,
                              p.profile_code, p.asset_code
                       FROM asset_constraint_profile_revisions r
                       JOIN asset_constraint_profiles p ON p.id = r.profile_id
                       WHERE r.profile_id = %s AND r.source_plan_code = %s""",
                    (profile["id"], plan_code),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    self.connection.commit()
                    return self._stringify(existing)
                current_revision = int(profile["current_revision"])
                if current_revision != expected_revision:
                    raise MaterialLibraryConflictError(
                        "CONSTRAINT_PROFILE_REVISION_CONFLICT: current revision changed"
                    )
                constraints: list[dict[str, Any]] = []
                if current_revision:
                    cursor.execute(
                        "SELECT constraints FROM asset_constraint_profile_revisions "
                        "WHERE profile_id = %s AND revision_number = %s",
                        (profile["id"], current_revision),
                    )
                    current = cursor.fetchone()
                    constraints = list(current["constraints"] or []) if current else []
                next_revision = current_revision + 1
                constraints.append(
                    {
                        "kind": "allowed_region",
                        "hard": True,
                        "parameters": {
                            **geometry,
                            "promoted_from_plan": plan_code,
                            "promotion_kind": "room_geometry",
                        },
                    }
                )
                canonical = self._canonical(constraints)
                cursor.execute(
                    """INSERT INTO asset_constraint_profile_revisions
                       (profile_id, revision_number, constraints, fingerprint_sha256, created_by,
                        change_reason, source_plan_code, source_profile_revision, source_room_override)
                       VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s::jsonb)""",
                    (
                        profile["id"], next_revision, canonical, self._fingerprint(canonical),
                        actor.strip(), reason.strip(), plan_code, current_revision,
                        json.dumps(override),
                    ),
                )
                cursor.execute(
                    "UPDATE asset_constraint_profiles SET current_revision = %s, updated_at = now() WHERE id = %s",
                    (next_revision, profile["id"]),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_constraint_profile(asset_code)

    def create_pack(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Repository callers that predate the API contract supplied only the
        # legacy role field.  Preserve those packages as total packs while the
        # validated API explicitly defaults new requests to classification.
        legacy_payload = "pack_kind" not in payload
        pack_kind = str(payload.get("pack_kind") or ("total" if legacy_payload else "classification"))
        role = str(payload.get("role") or "").strip() or None
        raw_entries = [
            ({**entry, "material_role": role} if legacy_payload and not entry.get("material_role") else entry)
            for entry in (payload.get("entries") or [])
        ]
        exclusive_roles = self._dedupe_codes(payload.get("exclusive_roles") or [])
        pack_constraints = list(payload.get("pack_constraints") or [])
        self._validate_pack_shape(pack_kind=pack_kind, role=role, entries=raw_entries)
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                entries = self._prepare_pack_entries(
                    cursor,
                    raw_entries,
                    pack_kind=pack_kind,
                    role=role,
                )
                revision_payload = self._revision_payload(
                    entries=entries,
                    exclusive_roles=exclusive_roles,
                    pack_constraints=pack_constraints,
                )
                canonical = self._canonical(revision_payload)
                pack_code = self._next_code(cursor, "AG-PACK", "material_pack")
                cursor.execute(
                    """INSERT INTO material_packs
                       (pack_code, title, pack_kind, role, description, current_revision, status)
                       VALUES (%s, %s, %s, %s, %s, 1, 'draft') RETURNING *""",
                    (pack_code, payload["title"], pack_kind, role, payload.get("description")),
                )
                pack = cursor.fetchone()
                cursor.execute(
                    """INSERT INTO material_pack_revisions
                       (pack_id, revision_number, status, entries, exclusive_roles, pack_constraints, fingerprint_sha256)
                       VALUES (%s, 1, 'draft', %s::jsonb, %s::jsonb, %s::jsonb, %s)""",
                    (
                        pack["id"],
                        json.dumps(entries),
                        json.dumps(exclusive_roles),
                        json.dumps(pack_constraints),
                        self._fingerprint(canonical),
                    ),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_pack(pack_code)  # type: ignore[return-value]

    def list_packs(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT p.pack_code, p.title, p.pack_kind, p.role, p.description, p.current_revision,
                       p.published_revision, p.status, p.created_at, p.updated_at, r.status AS revision_status,
                       r.entries, r.exclusive_roles, r.pack_constraints, r.fingerprint_sha256
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
                SELECT p.pack_code, p.title, p.pack_kind, p.role, p.description, p.current_revision,
                       p.published_revision, p.status, p.created_at, p.updated_at, r.status AS revision_status,
                       r.entries, r.exclusive_roles, r.pack_constraints, r.fingerprint_sha256
                FROM material_packs p
                JOIN material_pack_revisions r ON r.pack_id = p.id AND r.revision_number = p.current_revision
                WHERE p.pack_code = %s
                """,
                (pack_code,),
            )
            row = cursor.fetchone()
        return self._pack_read(row) if row else None

    def publish_pack(self, pack_code: str) -> dict[str, Any] | None:
        """Publish the current immutable revision without invalidating an older snapshot."""
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """SELECT id, current_revision, published_revision, status
                       FROM material_packs WHERE pack_code = %s FOR UPDATE""",
                    (pack_code,),
                )
                pack = cursor.fetchone()
                if pack is None:
                    self.connection.rollback()
                    return None
                if pack["status"] == "archived":
                    raise MaterialLibraryValidationError("Archived material packs cannot be published")
                cursor.execute(
                    """SELECT entries, exclusive_roles, pack_constraints
                       FROM material_pack_revisions
                       WHERE pack_id = %s AND revision_number = %s FOR UPDATE""",
                    (pack["id"], pack["current_revision"]),
                )
                revision = cursor.fetchone()
                if revision is None:
                    raise MaterialLibraryValidationError("Material pack current revision is missing")
                if not self._resolve_entries(list(revision["entries"] or [])):
                    raise MaterialLibraryValidationError("Material pack must resolve to at least one active asset before publication")
                previous_published = pack.get("published_revision")
                if previous_published and int(previous_published) != int(pack["current_revision"]):
                    cursor.execute(
                        """UPDATE material_pack_revisions SET status = 'superseded'
                           WHERE pack_id = %s AND revision_number = %s AND status = 'published'""",
                        (pack["id"], previous_published),
                    )
                cursor.execute(
                    """UPDATE material_pack_revisions SET status = 'published'
                       WHERE pack_id = %s AND revision_number = %s""",
                    (pack["id"], pack["current_revision"]),
                )
                cursor.execute(
                    """UPDATE material_packs
                       SET published_revision = current_revision, status = 'published', updated_at = now()
                       WHERE id = %s""",
                    (pack["id"],),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_pack(pack_code)

    def create_pack_revision(
        self,
        pack_code: str,
        *,
        expected_revision: int,
        entries: list[dict[str, Any]],
        exclusive_roles: list[str] | None = None,
        pack_constraints: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """SELECT id, current_revision, published_revision, status, pack_kind, role
                       FROM material_packs WHERE pack_code = %s FOR UPDATE""",
                    (pack_code,),
                )
                pack = cursor.fetchone()
                if pack is None:
                    self.connection.rollback()
                    return None
                if pack["status"] == "archived":
                    raise MaterialLibraryValidationError("Archived material packs cannot be revised")
                current_revision = int(pack["current_revision"])
                if current_revision != expected_revision:
                    raise MaterialLibraryValidationError(
                        "MATERIAL_PACK_REVISION_CONFLICT: current revision changed"
                    )
                self._validate_pack_shape(
                    pack_kind=str(pack["pack_kind"]), role=pack.get("role"), entries=entries
                )
                prepared_entries = self._prepare_pack_entries(
                    cursor,
                    entries,
                    pack_kind=str(pack["pack_kind"]),
                    role=pack.get("role"),
                )
                if exclusive_roles is None or pack_constraints is None:
                    cursor.execute(
                        """SELECT exclusive_roles, pack_constraints FROM material_pack_revisions
                           WHERE pack_id = %s AND revision_number = %s""",
                        (pack["id"], current_revision),
                    )
                    current = cursor.fetchone()
                    if current is None:
                        raise MaterialLibraryValidationError("Material pack current revision is missing")
                    if exclusive_roles is None:
                        exclusive_roles = list(current["exclusive_roles"] or [])
                    if pack_constraints is None:
                        pack_constraints = list(current["pack_constraints"] or [])
                normalized_exclusive_roles = self._dedupe_codes(exclusive_roles or [])
                normalized_pack_constraints = list(pack_constraints or [])
                revision_payload = self._revision_payload(
                    entries=prepared_entries,
                    exclusive_roles=normalized_exclusive_roles,
                    pack_constraints=normalized_pack_constraints,
                )
                canonical = self._canonical(revision_payload)
                fingerprint = self._fingerprint(canonical)
                next_revision = current_revision + 1
                cursor.execute(
                    """INSERT INTO material_pack_revisions
                       (pack_id, revision_number, status, entries, exclusive_roles, pack_constraints, fingerprint_sha256)
                       VALUES (%s, %s, 'draft', %s::jsonb, %s::jsonb, %s::jsonb, %s)""",
                    (
                        pack["id"], next_revision, json.dumps(prepared_entries),
                        json.dumps(normalized_exclusive_roles), json.dumps(normalized_pack_constraints), fingerprint,
                    ),
                )
                cursor.execute(
                    """UPDATE material_packs
                       SET current_revision = %s, status = 'draft', updated_at = now()
                       WHERE id = %s""",
                    (next_revision, pack["id"]),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_pack(pack_code)

    def list_pack_revisions(self, pack_code: str) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT revision_number, status, entries, exclusive_roles, pack_constraints,
                       fingerprint_sha256, created_at
                FROM material_pack_revisions
                WHERE pack_id = (SELECT id FROM material_packs WHERE pack_code = %s)
                ORDER BY revision_number DESC
                """,
                (pack_code,),
            )
            rows = cursor.fetchall()
        return [self._stringify(row) for row in rows]

    def resolve_published_packs(self, pack_codes: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        """Resolve selected published revisions and reject hard pack conflicts."""
        resolution = self.preview_published_pack_resolution(pack_codes)
        conflicts = list(resolution["conflicts"])
        if conflicts:
            codes = ", ".join(str(conflict["code"]) for conflict in conflicts)
            raise MaterialLibraryValidationError(f"MATERIAL_PACK_CONFLICT: {codes}")
        return list(resolution["pack_refs"]), list(resolution["resolved_asset_codes"])

    def preview_published_pack_resolution(self, pack_codes: list[str]) -> dict[str, Any]:
        """Return the exact revision whitelist, merged rules and explainable conflicts.

        This is used by the workbench before confirmation.  It deliberately
        returns conflicts rather than silently choosing a winner for mutually
        exclusive role domains.
        """
        refs: list[dict[str, Any]] = []
        for pack_code in self._dedupe_codes(pack_codes):
            published = self._get_published_pack(pack_code)
            if published is None:
                raise MaterialLibraryValidationError(f"Unknown material pack code: {pack_code}")
            if published.get("published_revision_number") is None:
                raise MaterialLibraryValidationError(f"Material pack must be published before selection: {pack_code}")
            if not published["resolved_asset_codes"]:
                raise MaterialLibraryValidationError(f"Published material pack resolves to no active assets: {pack_code}")
            refs.append(
                {
                    "pack_code": published["pack_code"],
                    "pack_kind": published["pack_kind"],
                    "revision_number": int(published["revision_number"]),
                    "fingerprint_sha256": published["fingerprint_sha256"],
                    "role": published.get("role"),
                    "revision_status": published["revision_status"],
                    "exclusive_roles": list(published.get("exclusive_roles") or []),
                    "pack_constraints": list(published.get("pack_constraints") or []),
                    "entries": list(published["entries"]),
                    "resolved_entries": list(published["resolved_entries"]),
                    "resolved_asset_codes": list(published["resolved_asset_codes"]),
                }
            )
        material_rules, rule_conflicts = self._merge_material_rules(refs)
        entry_requirements = [
            {
                "pack_code": ref["pack_code"],
                "revision_number": ref["revision_number"],
                "pack_kind": ref["pack_kind"],
                **entry,
            }
            for ref in refs
            for entry in ref["resolved_entries"]
        ]
        conflicts = [*self._exclusive_role_conflicts(refs), *rule_conflicts]
        fingerprint_payload = {
            "schema_version": "material-pack-resolution.v1",
            "pack_refs": refs,
            "entry_requirements": entry_requirements,
            "material_rules": material_rules,
            "conflicts": conflicts,
        }
        return {
            "schema_version": "material-pack-resolution.v1",
            "pack_refs": refs,
            "resolved_asset_codes": self._dedupe_codes(
                [asset_code for ref in refs for asset_code in ref["resolved_asset_codes"]]
            ),
            "entry_requirements": entry_requirements,
            "material_rules": material_rules,
            "conflicts": conflicts,
            "fingerprint_sha256": self._fingerprint(self._canonical(fingerprint_payload)),
        }

    def create_gap(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            code = self._next_code(cursor, "AG-GAP", "asset_gap")
            cursor.execute(
                """INSERT INTO asset_gaps
                   (gap_code, title, role, severity, gap_type, specification, source_context,
                    impact_summary, alternative_asset_codes)
                   VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb) RETURNING id""",
                (
                    code,
                    payload["title"],
                    payload["role"],
                    payload.get("severity", "medium"),
                    payload.get("gap_type", "material_missing"),
                    json.dumps(payload.get("specification") or {}),
                    json.dumps(payload.get("source_context") or {}),
                    payload.get("impact_summary"),
                    json.dumps(self._dedupe_codes(payload.get("alternative_asset_codes") or [])),
                ),
            )
            row = cursor.fetchone()
            self._record_gap_event(cursor, row["id"], None, "open", "library_user", {"created": True})
        self.connection.commit()
        return self.get_gap(code)  # type: ignore[return-value]

    def list_gaps(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(self._gap_select("ORDER BY g.updated_at DESC, g.gap_code"))
            rows = cursor.fetchall()
        return [self._gap_read(row) for row in rows]

    def get_gap(self, gap_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(self._gap_select("WHERE g.gap_code = %s"), (gap_code,))
            row = cursor.fetchone()
        return self._gap_read(row) if row else None

    def resolve_gap_refs(self, gap_codes: list[str]) -> list[dict[str, Any]]:
        """Freeze the current gap state for an explicit production-input reference."""
        refs: list[dict[str, Any]] = []
        for gap_code in self._dedupe_codes(gap_codes):
            gap = self.get_gap(gap_code)
            if gap is None:
                raise MaterialLibraryValidationError(f"Unknown asset gap code: {gap_code}")
            snapshot = {
                "gap_code": gap["gap_code"],
                "title": gap["title"],
                "role": gap["role"],
                "severity": gap["severity"],
                "status": gap["status"],
                "gap_type": gap["gap_type"],
                "impact_summary": gap.get("impact_summary"),
                "alternative_asset_codes": gap["alternative_asset_codes"],
                "resolution_asset_code": gap.get("resolution_asset_code"),
                "resolution_snapshot": gap["resolution_snapshot"],
            }
            refs.append({**snapshot, "fingerprint_sha256": self._fingerprint(self._canonical(snapshot))})
        return refs

    def preview_selection(self, *, role: str, carrier_kind: str) -> dict[str, Any]:
        """Return a deterministic, explainable candidate preview before planning.

        This is deliberately not a resolver: missing RightsGrant and geometric
        solver evidence remain explicit warnings instead of hidden assumptions.
        """
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT asset.asset_code, COALESCE(asset.title, asset.original_filename) AS title,
                          asset.media_kind, asset.material_roles, asset.execution_capability,
                          profile.profile_code, revision.revision_number, revision.fingerprint_sha256
                   FROM assets asset
                   LEFT JOIN asset_constraint_profiles profile ON profile.asset_id = asset.id
                   LEFT JOIN asset_constraint_profile_revisions revision
                     ON revision.profile_id = profile.id AND revision.revision_number = profile.current_revision
                   WHERE asset.deleted_at IS NULL
                   ORDER BY asset.asset_code"""
            )
            rows = cursor.fetchall()
        candidates: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        for row in rows:
            roles = list(row.get("material_roles") or [])
            capability = str(row.get("execution_capability") or "unclassified")
            exclusion_codes: list[str] = []
            if role not in roles:
                exclusion_codes.append("ROLE_MISMATCH")
            if capability in {"unavailable", "unclassified"}:
                exclusion_codes.append("EXECUTION_CAPABILITY_UNAVAILABLE")
            if carrier_kind == "live_room" and capability != "maitu_bound":
                exclusion_codes.append("LIVE_ROOM_MAITU_BINDING_REQUIRED")
            if exclusion_codes:
                excluded.append({"asset_code": row["asset_code"], "title": row["title"], "exclusion_codes": exclusion_codes})
                continue
            score_parts = {
                "role_match": 60,
                "execution_capability": 30 if capability == "maitu_bound" else 20,
                "constraint_profile": 10 if row["profile_code"] is not None else 0,
            }
            candidates.append(
                {
                    "asset_code": row["asset_code"],
                    "title": row["title"],
                    "media_kind": row["media_kind"],
                    "material_roles": roles,
                    "execution_capability": capability,
                    "score": sum(score_parts.values()),
                    "score_parts": score_parts,
                    "selection_reasons": ["ROLE_MATCH", f"CAPABILITY_{capability.upper()}"] + (["CONSTRAINT_PROFILE_BOUND"] if row["profile_code"] is not None else []),
                    "constraint_profile": {
                        "profile_code": row["profile_code"],
                        "revision_number": int(row["revision_number"]),
                        "fingerprint_sha256": row["fingerprint_sha256"],
                    } if row["profile_code"] is not None else None,
                }
            )
        candidates.sort(key=lambda item: (-int(item["score"]), str(item["asset_code"])))
        return {
            "schema_version": "deterministic-material-selection-preview.v1",
            "role": role,
            "carrier_kind": carrier_kind,
            "candidates": candidates,
            "excluded": excluded,
            "unverified_gates": ["RIGHTS_GRANT_NOT_IMPLEMENTED", "CONSTRAINT_SOLVER_NOT_RUN"],
        }

    def update_gap(self, gap_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SELECT * FROM asset_gaps WHERE gap_code = %s FOR UPDATE", (gap_code,))
                gap = cursor.fetchone()
                if gap is None:
                    self.connection.rollback()
                    return None
                previous_status = str(gap["status"])
                next_status = str(payload["status"])
                self._validate_gap_transition(previous_status, next_status)
                asset_code = payload.get("resolution_asset_code")
                snapshot: dict[str, Any] = dict(gap.get("resolution_snapshot") or {})
                if next_status in {"candidate_found", "resolved"}:
                    if next_status == "resolved" and gap.get("resolution_asset_code") != asset_code:
                        raise MaterialLibraryValidationError("ASSET_GAP_RESOLUTION_MUST_MATCH_CANDIDATE")
                    snapshot = self._gap_candidate_snapshot(cursor, str(asset_code), str(gap["role"]))
                waiver_reason = payload.get("waiver_reason") if next_status == "waived" else None
                if next_status == "waived" and not waiver_reason:
                    raise MaterialLibraryValidationError("ASSET_GAP_WAIVER_REASON_REQUIRED")
                resolved_at = "now()" if next_status in {"resolved", "waived"} else None
                cursor.execute(
                    """UPDATE asset_gaps
                       SET status = %s, resolution_asset_code = %s, resolution_snapshot = %s::jsonb,
                           resolution_evidence = %s::jsonb, resolved_by = %s,
                           resolved_at = CASE WHEN %s THEN now() ELSE resolved_at END,
                           waived_reason = %s, updated_at = now()
                       WHERE id = %s""",
                    (
                        next_status,
                        asset_code if next_status in {"candidate_found", "resolved"} else None,
                        json.dumps(snapshot),
                        json.dumps(payload.get("resolution_evidence") or {}),
                        payload.get("actor"),
                        resolved_at is not None,
                        waiver_reason,
                        gap["id"],
                    ),
                )
                self._record_gap_event(
                    cursor,
                    gap["id"],
                    previous_status,
                    next_status,
                    str(payload.get("actor") or "library_user"),
                    {
                        "resolution_asset_code": asset_code if next_status in {"candidate_found", "resolved"} else None,
                        "resolution_snapshot": snapshot if next_status in {"candidate_found", "resolved"} else {},
                        "resolution_evidence": payload.get("resolution_evidence") or {},
                        "waiver_reason": waiver_reason,
                    },
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_gap(gap_code)

    @staticmethod
    def _validate_gap_transition(previous_status: str, next_status: str) -> None:
        transitions = {
            "open": {"candidate_found", "waived", "obsolete"},
            "candidate_found": {"open", "resolved", "waived", "obsolete"},
            "resolved": {"obsolete"},
            "waived": {"obsolete"},
            "obsolete": set(),
        }
        if next_status not in transitions.get(previous_status, set()):
            raise MaterialLibraryValidationError(f"ASSET_GAP_INVALID_TRANSITION: {previous_status} -> {next_status}")

    def _gap_candidate_snapshot(self, cursor: Any, asset_code: str, role: str) -> dict[str, Any]:
        cursor.execute(
            """SELECT id, asset_code, title, media_kind, material_roles, execution_capability,
                      checksum_sha256, maitu_material_id, updated_at
               FROM assets WHERE asset_code = %s AND deleted_at IS NULL""",
            (asset_code,),
        )
        asset = cursor.fetchone()
        if asset is None:
            raise MaterialLibraryValidationError(f"ASSET_GAP_CANDIDATE_UNKNOWN_ASSET: {asset_code}")
        roles = list(asset.get("material_roles") or [])
        if role not in roles:
            raise MaterialLibraryValidationError(f"ASSET_GAP_CANDIDATE_ROLE_MISMATCH: {asset_code} lacks {role}")
        capability = str(asset.get("execution_capability") or "unclassified")
        if capability in {"unavailable", "unclassified"}:
            raise MaterialLibraryValidationError(f"ASSET_GAP_CANDIDATE_UNAVAILABLE: {asset_code}")
        cursor.execute(
            """SELECT p.profile_code, r.revision_number, r.fingerprint_sha256
               FROM asset_constraint_profiles p
               JOIN asset_constraint_profile_revisions r
                 ON r.profile_id = p.id AND r.revision_number = p.current_revision
               WHERE p.asset_id = %s""",
            (asset["id"],),
        )
        profile = cursor.fetchone()
        return {
            "asset_code": asset["asset_code"],
            "title": asset["title"],
            "media_kind": asset["media_kind"],
            "material_roles": roles,
            "execution_capability": capability,
            "checksum_sha256": asset["checksum_sha256"],
            "maitu_material_id": asset["maitu_material_id"],
            "asset_updated_at": asset["updated_at"].isoformat(),
            "constraint_profile": {
                "profile_code": profile["profile_code"],
                "revision_number": int(profile["revision_number"]),
                "fingerprint_sha256": profile["fingerprint_sha256"],
            } if profile else None,
        }

    def _record_gap_event(
        self,
        cursor: Any,
        gap_id: Any,
        previous_status: str | None,
        status: str,
        actor: str,
        payload: dict[str, Any],
    ) -> None:
        event_code = self._next_code(cursor, "AG-GAP-EVT", "asset_gap_resolution_event")
        cursor.execute(
            """INSERT INTO asset_gap_resolution_events
               (event_code, gap_id, previous_status, status, actor, payload)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb)""",
            (event_code, gap_id, previous_status, status, actor, json.dumps(payload)),
        )

    @staticmethod
    def _gap_select(suffix: str) -> str:
        return f"""
            SELECT g.*, COALESCE((
                SELECT jsonb_agg(jsonb_build_object(
                    'event_code', e.event_code,
                    'previous_status', e.previous_status,
                    'status', e.status,
                    'actor', e.actor,
                    'payload', e.payload,
                    'created_at', e.created_at
                ) ORDER BY e.created_at, e.event_code)
                FROM asset_gap_resolution_events e
                WHERE e.gap_id = g.id
            ), '[]'::jsonb) AS events
            FROM asset_gaps g
            {suffix}
        """

    def _gap_read(self, row: dict[str, Any]) -> dict[str, Any]:
        result = self._stringify(row)
        result["alternative_asset_codes"] = list(result.get("alternative_asset_codes") or [])
        result["resolution_snapshot"] = dict(result.get("resolution_snapshot") or {})
        result["resolution_evidence"] = dict(result.get("resolution_evidence") or {})
        result["events"] = list(result.get("events") or [])
        return result

    @staticmethod
    def _canonical(value: Any) -> str:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _normalized_override_geometry(override: dict[str, Any]) -> dict[str, float]:
        geometry = override.get("geometry")
        if not isinstance(geometry, dict):
            raise MaterialLibraryValidationError(
                "Only a room constraint override with geometry can be promoted"
            )
        expected = {"x", "y", "width", "height"}
        if set(geometry) != expected:
            raise MaterialLibraryValidationError("Room override geometry is invalid")
        normalized = {key: float(geometry[key]) for key in expected}
        if (
            not all(isfinite(value) for value in normalized.values())
            or normalized["x"] < 0
            or normalized["y"] < 0
            or normalized["width"] <= 0
            or normalized["height"] <= 0
            or normalized["x"] + normalized["width"] > 1
            or normalized["y"] + normalized["height"] > 1
        ):
            raise MaterialLibraryValidationError("Room override geometry is outside the normalized canvas")
        return normalized

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

    @staticmethod
    def _revision_payload(
        *,
        entries: list[dict[str, Any]],
        exclusive_roles: list[str],
        pack_constraints: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "entries": entries,
            "exclusive_roles": exclusive_roles,
            "pack_constraints": pack_constraints,
        }

    def _validate_pack_shape(
        self,
        *,
        pack_kind: str,
        role: str | None,
        entries: list[dict[str, Any]],
    ) -> None:
        if pack_kind not in {"total", "classification"}:
            raise MaterialLibraryValidationError("Material pack kind must be total or classification")
        if not entries:
            raise MaterialLibraryValidationError("Material pack must contain at least one entry")
        if pack_kind == "classification" and not role:
            raise MaterialLibraryValidationError("Classification material packs require a material role")
        for entry in entries:
            if not isinstance(entry, dict):
                raise MaterialLibraryValidationError("Material pack entries must be objects")
            kind = str(entry.get("selection_kind") or "")
            if kind not in {"asset", "group", "category_pack"}:
                raise MaterialLibraryValidationError("Material pack entry selection_kind is invalid")
            if pack_kind == "classification" and kind == "category_pack":
                raise MaterialLibraryValidationError("Classification material packs cannot include category packs")
            if not str(entry.get("selection_code") or "").strip():
                raise MaterialLibraryValidationError("Material pack entry selection_code is required")
            entry_role = str(entry.get("material_role") or "").strip() or None
            if pack_kind == "classification" and entry_role not in {None, role}:
                raise MaterialLibraryValidationError("Classification pack entries must use the pack material role")
            if pack_kind == "total" and not entry_role:
                raise MaterialLibraryValidationError("Total pack entries require material_role")
            mode = str(entry.get("mode") or "optional")
            if mode not in {"required", "optional", "alternative"}:
                raise MaterialLibraryValidationError("Material pack entry mode is invalid")
            try:
                minimum = int(entry.get("min_occurrences") or 0)
                maximum = entry.get("max_occurrences")
                maximum = int(maximum) if maximum is not None else None
            except (TypeError, ValueError) as exc:
                raise MaterialLibraryValidationError("Material pack occurrence bounds must be integers") from exc
            if minimum < 0 or (maximum is not None and (maximum < 1 or maximum < minimum)):
                raise MaterialLibraryValidationError("Material pack occurrence bounds are invalid")
            if mode in {"required", "alternative"} and minimum < 1:
                raise MaterialLibraryValidationError("Required and alternative material pack entries need min_occurrences")
            alternative_set_key = str(entry.get("alternative_set_key") or "").strip()
            if mode == "alternative" and not alternative_set_key:
                raise MaterialLibraryValidationError("Alternative material pack entries require alternative_set_key")
            if mode != "alternative" and alternative_set_key:
                raise MaterialLibraryValidationError("alternative_set_key is only valid for alternative entries")
            scope = entry.get("applicable_scope") or {"kind": "whole_room"}
            if not isinstance(scope, dict) or str(scope.get("kind") or "whole_room") not in {
                "whole_room", "scene_types", "scene_codes"
            }:
                raise MaterialLibraryValidationError("Material pack entry applicable_scope is invalid")

    def _prepare_pack_entries(
        self,
        cursor: Any,
        entries: list[dict[str, Any]],
        *,
        pack_kind: str,
        role: str | None,
    ) -> list[dict[str, Any]]:
        """Freeze group/category members into explicit assets before a revision is stored."""
        self._validate_pack_shape(pack_kind=pack_kind, role=role, entries=entries)
        prepared: list[dict[str, Any]] = []
        for index, raw_entry in enumerate(entries):
            entry = dict(raw_entry)
            entry_role = str(entry.get("material_role") or role or "").strip()
            normalized = {
                "material_role": entry_role,
                "mode": str(entry.get("mode") or "optional"),
                "min_occurrences": int(entry.get("min_occurrences") or 0),
                "max_occurrences": (
                    int(entry["max_occurrences"]) if entry.get("max_occurrences") is not None else None
                ),
                "applicable_scope": self._normalize_scope(entry.get("applicable_scope")),
                "pack_constraints": list(entry.get("pack_constraints") or []),
                "alternative_set_key": (
                    str(entry["alternative_set_key"]).strip()
                    if entry.get("alternative_set_key") is not None
                    else None
                ),
                "source_entry_index": index,
            }
            selection_kind = str(entry["selection_kind"])
            selection_code = str(entry["selection_code"]).strip()
            if selection_kind == "asset":
                self._require_assets(cursor, [selection_code])
                prepared.append({"selection_kind": "asset", "selection_code": selection_code, **normalized})
                continue
            if selection_kind == "group":
                asset_codes = self._group_asset_codes(cursor, selection_code)
                if not asset_codes:
                    raise MaterialLibraryValidationError(
                        f"Material pack group resolves to no active assets: {selection_code}"
                    )
                prepared.extend(
                    {
                        "selection_kind": "asset",
                        "selection_code": asset_code,
                        "source_group_code": selection_code,
                        **normalized,
                    }
                    for asset_code in asset_codes
                )
                continue
            category = self._published_category_pack(cursor, selection_code)
            if category is None:
                raise MaterialLibraryValidationError(
                    f"Category material pack must be published before inclusion: {selection_code}"
                )
            if str(category["pack_kind"]) != "classification":
                raise MaterialLibraryValidationError(
                    f"Total material packs cannot be included as category entries: {selection_code}"
                )
            category_role = str(category.get("role") or "")
            if entry_role != category_role:
                raise MaterialLibraryValidationError(
                    f"Category pack role mismatch for {selection_code}: expected {entry_role}, got {category_role}"
                )
            for source_entry in list(category["entries"] or []):
                for asset_code in self._entry_asset_codes(cursor, source_entry):
                    prepared.append(
                        {
                            "selection_kind": "asset",
                            "selection_code": asset_code,
                            "source_category_pack_code": selection_code,
                            "source_category_pack_revision": int(category["revision_number"]),
                            "source_category_entry": {
                                "selection_code": source_entry.get("selection_code"),
                                "source_group_code": source_entry.get("source_group_code"),
                            },
                            **normalized,
                        }
                    )
        self._validate_prepared_entry_roles(cursor, prepared, pack_kind=pack_kind, role=role)
        return prepared

    def _validate_prepared_entry_roles(
        self,
        cursor: Any,
        entries: list[dict[str, Any]],
        *,
        pack_kind: str,
        role: str | None,
    ) -> None:
        if pack_kind != "classification":
            return
        asset_codes = self._dedupe_codes([str(entry["selection_code"]) for entry in entries])
        cursor.execute(
            "SELECT asset_code, material_roles FROM assets WHERE asset_code = ANY(%s) AND deleted_at IS NULL",
            (asset_codes,),
        )
        invalid = sorted(
            row["asset_code"]
            for row in cursor.fetchall()
            if role not in list(row.get("material_roles") or [])
        )
        if invalid:
            raise MaterialLibraryValidationError(
                f"Classification pack role {role} is missing on assets: {', '.join(invalid)}"
            )

    @staticmethod
    def _normalize_scope(value: Any) -> dict[str, Any]:
        scope = dict(value) if isinstance(value, dict) else {}
        kind = str(scope.get("kind") or "whole_room")
        return {
            "kind": kind,
            "scene_types": MaterialLibraryRepository._dedupe_codes(scope.get("scene_types") or []),
            "scene_codes": MaterialLibraryRepository._dedupe_codes(scope.get("scene_codes") or []),
        }

    def _group_asset_codes(self, cursor: Any, group_code: str) -> list[str]:
        cursor.execute(
            """SELECT a.asset_code FROM asset_group_members gm
               JOIN asset_groups g ON g.id = gm.group_id
               JOIN assets a ON a.id = gm.asset_id AND a.deleted_at IS NULL
               WHERE g.group_code = %s ORDER BY a.asset_code""",
            (group_code,),
        )
        rows = cursor.fetchall()
        if not rows:
            cursor.execute("SELECT 1 FROM asset_groups WHERE group_code = %s", (group_code,))
            if cursor.fetchone() is None:
                raise MaterialLibraryValidationError(f"Unknown asset group code: {group_code}")
        return [str(row["asset_code"]) for row in rows]

    def _published_category_pack(self, cursor: Any, pack_code: str) -> dict[str, Any] | None:
        cursor.execute(
            """SELECT p.pack_code, p.pack_kind, p.role, p.published_revision,
                      r.revision_number, r.entries, r.fingerprint_sha256
               FROM material_packs p
               JOIN material_pack_revisions r
                 ON r.pack_id = p.id AND r.revision_number = p.published_revision
               WHERE p.pack_code = %s""",
            (pack_code,),
        )
        return cursor.fetchone()

    def _entry_asset_codes(self, cursor: Any, entry: dict[str, Any]) -> list[str]:
        if str(entry.get("selection_kind") or "") == "asset":
            asset_code = str(entry.get("selection_code") or "").strip()
            if not asset_code:
                return []
            cursor.execute(
                "SELECT asset_code FROM assets WHERE asset_code = %s AND deleted_at IS NULL",
                (asset_code,),
            )
            return [asset_code] if cursor.fetchone() is not None else []
        if str(entry.get("selection_kind") or "") == "group":
            return self._group_asset_codes(cursor, str(entry.get("selection_code") or ""))
        return []

    def _resolve_entries(self, entries: list[dict[str, Any]]) -> list[str]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            return self._dedupe_codes(
                [asset_code for entry in entries for asset_code in self._entry_asset_codes(cursor, entry)]
            )

    def _group_read(self, row: dict[str, Any]) -> dict[str, Any]:
        result = self._stringify(row)
        result["asset_codes"] = list(result.get("asset_codes") or [])
        result["asset_count"] = len(result["asset_codes"])
        return result

    def _get_published_pack(self, pack_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT p.pack_code, p.title, p.pack_kind, p.role, p.description,
                          p.current_revision, p.published_revision, p.status,
                          p.created_at, p.updated_at, r.status AS revision_status,
                          r.entries, r.exclusive_roles, r.pack_constraints, r.fingerprint_sha256
                   FROM material_packs p
                   LEFT JOIN material_pack_revisions r
                     ON r.pack_id = p.id AND r.revision_number = p.published_revision
                   WHERE p.pack_code = %s""",
                (pack_code,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        if row.get("published_revision") is None:
            return {
                "pack_code": row["pack_code"],
                "published_revision_number": None,
                "resolved_asset_codes": [],
            }
        published_row = {**row, "revision_number": int(row["published_revision"])}
        result = self._pack_read(published_row)
        result["published_revision_number"] = int(row["published_revision"])
        return result

    def _resolved_entry_read(self, entry: dict[str, Any], index: int) -> dict[str, Any]:
        source = dict(entry)
        asset_codes = self._resolve_entries([source])
        source_index = int(source.get("source_entry_index") if source.get("source_entry_index") is not None else index)
        return {
            "entry_key": f"entry-{source_index + 1}",
            "selection_kind": source.get("selection_kind"),
            "selection_code": source.get("selection_code"),
            "material_role": source.get("material_role"),
            "mode": source.get("mode") or "optional",
            "min_occurrences": int(source.get("min_occurrences") or 0),
            "max_occurrences": source.get("max_occurrences"),
            "applicable_scope": self._normalize_scope(source.get("applicable_scope")),
            "pack_constraints": list(source.get("pack_constraints") or []),
            "alternative_set_key": source.get("alternative_set_key"),
            "source_group_code": source.get("source_group_code"),
            "source_category_pack_code": source.get("source_category_pack_code"),
            "source_category_pack_revision": source.get("source_category_pack_revision"),
            "resolved_asset_codes": asset_codes,
        }

    @staticmethod
    def _mode_strength(mode: str) -> int:
        return {"optional": 1, "alternative": 2, "required": 3}.get(mode, 0)

    def _merge_material_rules(
        self, refs: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        by_asset_role: dict[tuple[str, str], dict[str, Any]] = {}
        conflicts: list[dict[str, Any]] = []
        for ref in refs:
            for entry in ref.get("resolved_entries") or []:
                if not isinstance(entry, dict):
                    continue
                for asset_code in entry.get("resolved_asset_codes") or []:
                    role = str(entry.get("material_role") or "")
                    key = (str(asset_code), role)
                    source = {
                        "pack_code": ref["pack_code"],
                        "revision_number": ref["revision_number"],
                        "entry_key": entry["entry_key"],
                        "mode": entry["mode"],
                        "min_occurrences": entry["min_occurrences"],
                        "max_occurrences": entry.get("max_occurrences"),
                        "applicable_scope": entry["applicable_scope"],
                        "alternative_set_key": entry.get("alternative_set_key"),
                        "source_group_code": entry.get("source_group_code"),
                        "source_category_pack_code": entry.get("source_category_pack_code"),
                    }
                    current = by_asset_role.get(key)
                    if current is None:
                        by_asset_role[key] = {
                            "asset_code": str(asset_code),
                            "material_role": role,
                            "mode": entry["mode"],
                            "min_occurrences": int(entry["min_occurrences"]),
                            "max_occurrences": entry.get("max_occurrences"),
                            "applicable_scopes": [entry["applicable_scope"]],
                            "hard_constraints": [
                                *list(ref.get("pack_constraints") or []),
                                *list(entry.get("pack_constraints") or []),
                            ],
                            "sources": [source],
                        }
                        continue
                    if self._mode_strength(str(entry["mode"])) > self._mode_strength(str(current["mode"])):
                        current["mode"] = entry["mode"]
                    current["min_occurrences"] = max(
                        int(current["min_occurrences"]), int(entry["min_occurrences"])
                    )
                    maxima = [
                        value for value in (current.get("max_occurrences"), entry.get("max_occurrences"))
                        if value is not None
                    ]
                    current["max_occurrences"] = min(maxima) if maxima else None
                    if entry["applicable_scope"] not in current["applicable_scopes"]:
                        current["applicable_scopes"].append(entry["applicable_scope"])
                    current["hard_constraints"].extend(
                        [*list(ref.get("pack_constraints") or []), *list(entry.get("pack_constraints") or [])]
                    )
                    current["sources"].append(source)
        rules = sorted(by_asset_role.values(), key=lambda rule: (rule["material_role"], rule["asset_code"]))
        for rule in rules:
            maximum = rule.get("max_occurrences")
            if maximum is not None and int(maximum) < int(rule["min_occurrences"]):
                conflicts.append(
                    {
                        "code": "MATERIAL_PACK_OCCURRENCE_CONFLICT",
                        "asset_code": rule["asset_code"],
                        "material_role": rule["material_role"],
                        "sources": rule["sources"],
                        "remediation": "调整同一素材的 min/max occurrences 或移除冲突来源",
                    }
                )
        return rules, conflicts

    @staticmethod
    def _exclusive_role_conflicts(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        for role in sorted({role for ref in refs for role in ref.get("exclusive_roles") or []}):
            scoped = [
                ref for ref in refs
                if role in (ref.get("exclusive_roles") or [])
            ]
            for index, left in enumerate(scoped):
                left_assets = {
                    asset_code
                    for entry in left.get("resolved_entries") or []
                    if entry.get("material_role") == role
                    for asset_code in entry.get("resolved_asset_codes") or []
                }
                for right in scoped[index + 1:]:
                    right_assets = {
                        asset_code
                        for entry in right.get("resolved_entries") or []
                        if entry.get("material_role") == role
                        for asset_code in entry.get("resolved_asset_codes") or []
                    }
                    if left_assets != right_assets:
                        conflicts.append(
                            {
                                "code": "MATERIAL_PACK_EXCLUSIVE_ROLE_CONFLICT",
                                "material_role": role,
                                "pack_codes": [left["pack_code"], right["pack_code"]],
                                "left_asset_codes": sorted(left_assets),
                                "right_asset_codes": sorted(right_assets),
                                "remediation": "对该角色域只保留一个排他素材包，或将其中一个改为非排他",
                            }
                        )
        return conflicts

    def _pack_read(self, row: dict[str, Any]) -> dict[str, Any]:
        result = self._stringify(row)
        result["revision_number"] = int(result.get("revision_number") or result.pop("current_revision"))
        result["pack_kind"] = str(result.get("pack_kind") or "total")
        result["revision_status"] = str(result.get("revision_status") or result.get("status") or "draft")
        result["published_revision_number"] = (
            int(result["published_revision"]) if result.get("published_revision") is not None else None
        )
        result["exclusive_roles"] = self._dedupe_codes(result.get("exclusive_roles") or [])
        result["pack_constraints"] = list(result.get("pack_constraints") or [])
        entries = list(result.get("entries") or [])
        result["entries"] = entries
        by_key: dict[str, dict[str, Any]] = {}
        for index, entry in enumerate(entries):
            resolved = self._resolved_entry_read(entry, index)
            existing = by_key.get(resolved["entry_key"])
            if existing is None:
                by_key[resolved["entry_key"]] = resolved
            else:
                existing["resolved_asset_codes"] = self._dedupe_codes(
                    [*existing["resolved_asset_codes"], *resolved["resolved_asset_codes"]]
                )
        result["resolved_entries"] = list(by_key.values())
        result["resolved_asset_codes"] = self._dedupe_codes(
            [asset_code for entry in result["resolved_entries"] for asset_code in entry["resolved_asset_codes"]]
        )
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
