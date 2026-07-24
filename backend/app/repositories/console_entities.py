from __future__ import annotations

from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row


def structured_diff(before: Any, after: Any, *, path: str = "$") -> list[dict[str, Any]]:
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            child_path = f"{path}.{key}"
            if key not in before:
                changes.append({"path": child_path, "change": "added", "before": None, "after": after[key]})
            elif key not in after:
                changes.append({"path": child_path, "change": "removed", "before": before[key], "after": None})
            else:
                changes.extend(structured_diff(before[key], after[key], path=child_path))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        changes = []
        for index in range(max(len(before), len(after))):
            child_path = f"{path}[{index}]"
            if index >= len(before):
                changes.append({"path": child_path, "change": "added", "before": None, "after": after[index]})
            elif index >= len(after):
                changes.append({"path": child_path, "change": "removed", "before": before[index], "after": None})
            else:
                changes.extend(structured_diff(before[index], after[index], path=child_path))
        return changes
    return [{"path": path, "change": "changed", "before": before, "after": after}]


class ConsoleEntityRepository:
    SUPPORTED_TYPES = {"asset", "content_project", "live_room_template", "workflow_run", "release"}

    def __init__(self, connection: Connection):
        self.connection = connection

    def get_entity(
        self,
        entity_type: str,
        entity_code: str,
        *,
        from_revision: int | None = None,
        to_revision: int | None = None,
    ) -> dict[str, Any] | None:
        if entity_type not in self.SUPPORTED_TYPES:
            return None
        loader = getattr(self, f"_load_{entity_type}")
        entity = loader(entity_code)
        if entity is None:
            return None
        revisions = entity["revisions"]
        by_revision = {row["revision"]: row for row in revisions}
        selected_to = to_revision or entity["current_revision"]
        selected_from = from_revision
        if selected_from is None:
            earlier = sorted(revision for revision in by_revision if revision < selected_to)
            selected_from = earlier[-1] if earlier else selected_to
        before = by_revision.get(selected_from)
        after = by_revision.get(selected_to)
        if before is None or after is None:
            entity["diff"] = {
                "from_revision": selected_from,
                "to_revision": selected_to,
                "available": False,
                "changes": [],
            }
        else:
            entity["diff"] = {
                "from_revision": selected_from,
                "to_revision": selected_to,
                "available": True,
                "changes": structured_diff(before["snapshot"], after["snapshot"])[:500],
            }
        entity["revisions"] = sorted(revisions, key=lambda row: row["revision"], reverse=True)
        return entity

    def _load_asset(self, code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT asset_code, COALESCE(title, original_filename) AS title, status,
                       asset_type, source_system, source_type, original_filename,
                       checksum_sha256, maitu_category, maitu_project_code,
                       maitu_scene_name, maitu_layer_name, maitu_slot_code,
                       layer_left, layer_top, layer_width, layer_height, layer_z_index,
                       duplicate_group, created_at, updated_at
                FROM assets WHERE asset_code = %s AND deleted_at IS NULL
                """,
                (code,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            snapshot = {
                key: value
                for key, value in dict(row).items()
                if key not in {"created_at", "updated_at", "title", "status"}
            }
            cursor.execute(
                """
                SELECT DISTINCT plan.build_plan_code AS entity_code, plan.status,
                       '/production/live-rooms?build_plan=' || plan.build_plan_code AS href
                FROM maitu_live_room_build_plan_operations AS operation
                JOIN maitu_live_room_build_plans AS plan ON plan.id = operation.build_plan_id
                WHERE operation.selected_asset_code = %s
                ORDER BY plan.build_plan_code
                """,
                (code,),
            )
            used_by = [
                self._relation("used_by_build_plan", "build_plan", item["entity_code"], item["href"], item["status"])
                for item in cursor.fetchall()
            ]
        sources = []
        if row["source_system"]:
            sources.append(self._relation("imported_from", "source_system", row["source_system"], None, None))
        return self._entity(
            "asset",
            code,
            row["title"],
            row["status"],
            1,
            f"/assets/library?asset={code}",
            [{
                "revision": 1,
                "status": row["status"],
                "schema_version": "legacy-asset-observation.v1",
                "created_at": row["updated_at"],
                "created_by": None,
                "fingerprint": row["checksum_sha256"],
                "snapshot": snapshot,
            }],
            sources,
            used_by,
        )

    def _load_content_project(self, code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM content_projects WHERE project_code = %s", (code,))
            project = cursor.fetchone()
            if project is None:
                return None
            cursor.execute(
                """
                SELECT revision_number AS revision, status, schema_version, created_at,
                       created_by, fingerprint_sha256 AS fingerprint,
                       jsonb_build_object(
                           'generation_goal', generation_goal,
                           'content', content,
                           'source_revision_refs', source_revision_refs,
                           'producer_role', producer_role,
                           'producer_strategy_revision', producer_strategy_revision
                       ) AS snapshot,
                       source_revision_refs
                FROM content_project_revisions
                WHERE project_code = %s ORDER BY revision_number
                """,
                (code,),
            )
            revision_rows = cursor.fetchall()
            revisions = [self._revision(row) for row in revision_rows]
            sources = self._sources(revision_rows)
            cursor.execute("SELECT variant_code FROM production_variants WHERE project_code = %s", (code,))
            subject_codes = [code, *(row["variant_code"] for row in cursor.fetchall())]
            used_by = self._runs_and_releases(cursor, subject_codes)
        return self._entity(
            "content_project",
            code,
            project["title"],
            project["status"],
            max(project["current_revision_number"], revisions[-1]["revision"] if revisions else 1),
            f"/content/projects?project={code}",
            revisions,
            sources,
            used_by,
        )

    def _load_live_room_template(self, code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM live_room_templates WHERE template_code = %s", (code,))
            template = cursor.fetchone()
            if template is None:
                return None
            cursor.execute(
                """
                SELECT revision_number AS revision, status, contract_version AS schema_version,
                       created_at, created_by, content_fingerprint AS fingerprint,
                       jsonb_build_object(
                           'canvas', canvas, 'scenes', scenes, 'components', components,
                           'audio_policy', audio_policy, 'provenance', provenance,
                           'confidence', confidence, 'review_status', review_status,
                           'source_session_code', source_session_code
                       ) AS snapshot,
                       provenance AS source_revision_refs,
                       source_session_code
                FROM live_room_template_revisions
                WHERE template_code = %s ORDER BY revision_number
                """,
                (code,),
            )
            revision_rows = cursor.fetchall()
            revisions = [self._revision(row) for row in revision_rows]
            sources = self._sources(revision_rows)
            for row in revision_rows:
                if row["source_session_code"]:
                    sources.append(self._relation(
                        "derived_from", "capture_session", row["source_session_code"],
                        f"/research/live-sources?view=sessions&session={row['source_session_code']}", None,
                    ))
            cursor.execute(
                """
                SELECT run_code AS entity_code, status,
                       '/production/live-rooms?run=' || run_code AS href
                FROM maitu_workbench_runs WHERE reference_template_code = %s
                ORDER BY updated_at DESC
                """,
                (code,),
            )
            used_by = [
                self._relation("used_by_run", "legacy_workbench_run", row["entity_code"], row["href"], row["status"])
                for row in cursor.fetchall()
            ]
        current = max((row["revision"] for row in revisions), default=1)
        return self._entity(
            "live_room_template", code, template["name"], template["status"], current,
            f"/research/live-sources?template={code}", revisions, self._dedupe(sources), used_by,
        )

    def _load_workflow_run(self, code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM workflow_runs WHERE run_code = %s", (code,))
            run = cursor.fetchone()
            if run is None:
                return None
            cursor.execute(
                """
                SELECT row_number() OVER (ORDER BY occurred_at, id)::integer AS revision,
                       to_status AS status, 'workflow-status.v1'::varchar AS schema_version,
                       occurred_at AS created_at, actor_id AS created_by,
                       NULL::varchar AS fingerprint,
                       jsonb_build_object(
                           'from_status', from_status, 'to_status', to_status,
                           'reason_code', reason_code, 'actor_type', actor_type,
                           'actor_id', actor_id, 'evidence', evidence
                       ) AS snapshot
                FROM workflow_status_history WHERE run_id = %s
                ORDER BY occurred_at, id
                """,
                (run["id"],),
            )
            revisions = [self._revision(row) for row in cursor.fetchall()]
            if not revisions:
                revisions = [{
                    "revision": 1, "status": run["status"], "schema_version": run["schema_version"],
                    "created_at": run["created_at"], "created_by": run["requested_by"], "fingerprint": None,
                    "snapshot": {"status": run["status"], "subject_code": run["subject_code"]},
                }]
            sources = [self._relation(
                "operates_on", run["subject_type"], run["subject_code"],
                self._href(run["subject_type"], run["subject_code"]), None, run["subject_revision"],
            )]
            cursor.execute(
                """
                SELECT child.run_code AS entity_code, child.status,
                       '/governance/runs?run=' || child.run_code AS href
                FROM workflow_runs AS child WHERE child.parent_run_id = %s
                ORDER BY child.created_at
                """,
                (run["id"],),
            )
            used_by = [
                self._relation("parent_of", "workflow_run", row["entity_code"], row["href"], row["status"])
                for row in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT DISTINCT release.release_code AS entity_code, release.status,
                       '/production/releases?release=' || release.release_code AS href
                FROM release_manifests AS manifest
                JOIN releases AS release ON release.id = manifest.release_id
                WHERE manifest.lineage_snapshot->>'run_code' = %s
                   OR COALESCE(manifest.lineage_snapshot->'run_codes', '[]'::jsonb) ? %s
                """,
                (code, code),
            )
            used_by.extend(
                self._relation("used_by_release", "release", row["entity_code"], row["href"], row["status"])
                for row in cursor.fetchall()
            )
        return self._entity(
            "workflow_run", code, f"{run['workflow_type']} / {run['subject_code']}", run["status"],
            len(revisions), f"/governance/runs?run={code}", revisions, sources, used_by,
        )

    def _load_release(self, code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM releases WHERE release_code = %s", (code,))
            release = cursor.fetchone()
            if release is None:
                return None
            cursor.execute(
                """
                SELECT revision_number AS revision, 'sealed'::varchar AS status,
                       schema_version, created_at, NULL::varchar AS created_by,
                       manifest_fingerprint AS fingerprint,
                       jsonb_build_object(
                           'subject_refs', subject_refs, 'artifact_refs', artifact_refs,
                           'rights_snapshot', rights_snapshot, 'quality_snapshot', quality_snapshot,
                           'lineage_snapshot', lineage_snapshot, 'carrier_facet', carrier_facet
                       ) AS snapshot,
                       subject_refs AS source_revision_refs
                FROM release_manifests WHERE release_id = %s ORDER BY revision_number
                """,
                (release["id"],),
            )
            revision_rows = cursor.fetchall()
            revisions = [self._revision(row) for row in revision_rows]
            sources = [self._relation(
                "releases", release["subject_type"], release["subject_code"],
                self._href(release["subject_type"], release["subject_code"]), None,
                release["subject_revision"],
            )]
            sources.extend(self._sources(revision_rows))
            cursor.execute(
                """
                SELECT delivery_code AS entity_code, status,
                       '/production/releases?release=' || release_code || '&delivery=' || delivery_code AS href
                FROM delivery_attempts WHERE release_id = %s ORDER BY created_at
                """,
                (release["id"],),
            )
            used_by = [
                self._relation("delivered_by", "delivery", row["entity_code"], row["href"], row["status"])
                for row in cursor.fetchall()
            ]
        current = max(release["current_manifest_revision"], revisions[-1]["revision"] if revisions else 1)
        return self._entity(
            "release", code, f"{release['carrier_kind']} / {release['subject_code']}", release["status"],
            current, f"/production/releases?release={code}", revisions, self._dedupe(sources), used_by,
        )

    def _runs_and_releases(self, cursor: Any, subject_codes: list[str]) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT run_code AS entity_code, status, '/governance/runs?run=' || run_code AS href
            FROM workflow_runs WHERE subject_code = ANY(%s) ORDER BY updated_at DESC
            """,
            (subject_codes,),
        )
        used_by = [
            self._relation("used_by_run", "workflow_run", row["entity_code"], row["href"], row["status"])
            for row in cursor.fetchall()
        ]
        cursor.execute(
            """
            SELECT release_code AS entity_code, status,
                   '/production/releases?release=' || release_code AS href
            FROM releases WHERE subject_code = ANY(%s) ORDER BY updated_at DESC
            """,
            (subject_codes,),
        )
        used_by.extend(
            self._relation("used_by_release", "release", row["entity_code"], row["href"], row["status"])
            for row in cursor.fetchall()
        )
        return used_by

    @staticmethod
    def _revision(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "revision": row["revision"], "status": row["status"],
            "schema_version": row["schema_version"], "created_at": row["created_at"],
            "created_by": row.get("created_by"), "fingerprint": row.get("fingerprint"),
            "snapshot": row["snapshot"],
        }

    def _sources(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        for row in rows:
            raw = row.get("source_revision_refs")
            refs = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                entity_type = str(ref.get("object_type") or ref.get("source_type") or ref.get("kind") or "revision_ref")
                code = next((str(ref[key]) for key in (
                    "code", "template_code", "fact_card_code", "snapshot_code", "project_code",
                ) if ref.get(key)), None)
                if code:
                    revision = ref.get("revision") or ref.get("revision_number")
                    sources.append(self._relation(
                        "derived_from", entity_type, code, self._href(entity_type, code), None,
                        int(revision) if isinstance(revision, int) else None,
                    ))
        return self._dedupe(sources)

    @staticmethod
    def _href(entity_type: str, code: str) -> str | None:
        routes = {
            "asset": "/assets/library?asset=",
            "content_project": "/content/projects?project=",
            "live_room_template": "/research/live-sources?template=",
            "workflow_run": "/governance/runs?run=",
            "release": "/production/releases?release=",
            "capture_session": "/research/live-sources?view=sessions&session=",
        }
        prefix = routes.get(entity_type)
        return f"{prefix}{code}" if prefix else None

    @staticmethod
    def _relation(
        relation_type: str,
        entity_type: str,
        entity_code: str,
        href: str | None,
        status: str | None,
        revision: int | None = None,
    ) -> dict[str, Any]:
        return {
            "relation_type": relation_type, "entity_type": entity_type,
            "entity_code": entity_code, "revision": revision, "status": status,
            "href": href, "mapping_quality": "verified",
        }

    @staticmethod
    def _dedupe(relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: dict[tuple[Any, ...], dict[str, Any]] = {}
        for relation in relations:
            key = (
                relation["relation_type"], relation["entity_type"],
                relation["entity_code"], relation.get("revision"),
            )
            unique[key] = relation
        return list(unique.values())

    @staticmethod
    def _entity(
        entity_type: str,
        code: str,
        title: str,
        status: str,
        current_revision: int,
        canonical_href: str,
        revisions: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        used_by: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "entity_type": entity_type, "entity_code": code, "title": title,
            "status": status, "current_revision": current_revision,
            "canonical_href": canonical_href, "source_of_truth": "postgresql",
            "revisions": revisions, "sources": sources, "used_by": used_by,
        }
