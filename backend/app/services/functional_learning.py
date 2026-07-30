from __future__ import annotations
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from app.domain.contracts import canonical_fingerprint
from app.domain.errors import DomainValidationError
from app.repositories.content_core import ContentCoreRepository
from app.repositories.content_production import ContentProductionRepository
from app.services.functional_content import FunctionalContentService


RECOMMENDATION_STRATEGY_VERSION = "effect-aware-advisory.v1"
MINIMUM_EFFECT_SESSION_COUNT = 3


class FunctionalLearningService:
    def __init__(self, connection: Connection):
        self.connection = connection

    def create_decision(self, p: dict[str, Any]) -> dict[str, Any]:
        try:
            with self.connection.cursor(row_factory=dict_row) as c:
                row = self._insert_decision(c, p)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return row

    def list_decisions(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as c:
            c.execute("SELECT * FROM functional_decision_logs ORDER BY created_at DESC")
            return [dict(x) for x in c.fetchall()]

    def create_effect_estimate(self, p: dict[str, Any]) -> dict[str, Any]:
        try:
            with self.connection.cursor(row_factory=dict_row) as c:
                c.execute(
                    "SELECT * FROM functional_attribution_reports WHERE report_code = %s",
                    (p["attribution_report_code"],),
                )
                report = c.fetchone()
                if report is None:
                    raise DomainValidationError(
                        "EFFECT_ESTIMATE_REPORT_NOT_FOUND",
                        "The selected attribution report does not exist",
                        details={"attribution_report_code": p["attribution_report_code"]},
                    )
                report_results = report["results"] or {}
                groups = report_results.get("groups") or {}
                metadata = report_results.get("metadata") or {}
                quality = report.get("quality_snapshot") or {}
                selected_session_count = int(
                    metadata.get("selected_session_count")
                    or quality.get("selected_session_count")
                    or len(report.get("session_codes") or [])
                )
                observed_session_count = int(
                    metadata.get("observed_session_count")
                    or quality.get("observed_session_count")
                    or 0
                )
                metric_definition_state = str(
                    metadata.get("metric_definition_state")
                    or quality.get("metric_definition_state")
                    or "metric_unpinned"
                )
                requested_level = str(p.get("evidence_level") or "descriptive")
                association_blockers: list[str] = []
                if report["status"] != "published_descriptive":
                    association_blockers.append("REPORT_NOT_PUBLISHED_DESCRIPTIVE")
                if selected_session_count < MINIMUM_EFFECT_SESSION_COUNT:
                    association_blockers.append("EFFECT_SAMPLE_SIZE_BELOW_MINIMUM")
                if observed_session_count < MINIMUM_EFFECT_SESSION_COUNT:
                    association_blockers.append("OBSERVED_SAMPLE_SIZE_BELOW_MINIMUM")
                if metric_definition_state != "metric_pinned":
                    association_blockers.append("METRIC_DEFINITION_NOT_PINNED")
                if requested_level == "associational" and association_blockers:
                    raise DomainValidationError(
                        "EFFECT_ASSOCIATIONAL_EVIDENCE_INELIGIBLE",
                        "The selected report is not eligible for an associational effect signal",
                        details={"blockers": association_blockers},
                    )
                eligibility = {
                    "report_code": report["report_code"],
                    "report_created_at": report["created_at"].isoformat(),
                    "evidence_level": requested_level,
                    "selected_session_count": selected_session_count,
                    "observed_session_count": observed_session_count,
                    "metric_definition_state": metric_definition_state,
                    "has_groups": bool(groups),
                    "minimum_recommendation_session_count": MINIMUM_EFFECT_SESSION_COUNT,
                    "association_blockers": association_blockers,
                    "recommendation_eligible": requested_level == "associational" and not association_blockers,
                    "qualification": (
                        "associational_advisory"
                        if requested_level == "associational"
                        else "descriptive_hint_only"
                    ),
                }
                payload = {
                    "report_groups": groups,
                    "report_metadata": metadata,
                    "report_metric_definition_ref": report.get("metric_definition_ref"),
                    "subject_snapshot": self._subject_snapshot(c, p["subject_type"], p["subject_code"]),
                }
                effect_code = self._next(c, "EFFECT", "functional_effect_estimate")
                fingerprint = canonical_fingerprint(
                    {
                        "effect_code": effect_code,
                        "revision_number": 1,
                        "attribution_report_code": report["report_code"],
                        "subject_type": p["subject_type"],
                        "subject_code": p["subject_code"],
                        "metric_key": report["metric_key"],
                        "context": p["context"],
                        "effect_payload": payload,
                        "eligibility_snapshot": eligibility,
                        "note": p["note"],
                    }
                )
                c.execute(
                    """INSERT INTO functional_effect_estimates
                       (effect_code,revision_number,attribution_report_code,subject_type,subject_code,
                        metric_key,evidence_level,status,context,effect_payload,eligibility_snapshot,
                        note,fingerprint_sha256)
                       VALUES (%s,1,%s,%s,%s,%s,%s,'candidate',%s,%s,%s,%s,%s)
                       RETURNING *""",
                    (
                        effect_code,
                        report["report_code"],
                        p["subject_type"],
                        p["subject_code"],
                        report["metric_key"],
                        requested_level,
                        Jsonb(p["context"]),
                        Jsonb(payload),
                        Jsonb(eligibility),
                        p["note"],
                        fingerprint,
                    ),
                )
                row = c.fetchone()
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return dict(row)

    def list_effect_estimates(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as c:
            c.execute(
                "SELECT * FROM functional_effect_estimates ORDER BY created_at DESC, effect_code"
            )
            return [dict(row) for row in c.fetchall()]

    def recommendations(self, project_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as c:
            c.execute(
                """SELECT revision.project_code, revision.revision_number,
                          revision.content, revision.generation_goal,
                          revision.fingerprint_sha256, project.title
                   FROM content_projects AS project
                   JOIN content_project_revisions AS revision
                     ON revision.project_id = project.id
                    AND revision.revision_number = project.current_revision_number
                   WHERE project.project_code = %s""",
                (project_code,),
            )
            project = c.fetchone()
            if project is None:
                return None
            c.execute(
                """SELECT template.template_code, template.name, template.description,
                          revision.revision_number, revision.content_readiness,
                          revision.buildability, revision.content_strategy,
                          revision.confidence
                   FROM live_room_templates AS template
                   JOIN live_room_template_revisions AS revision
                     ON revision.id = template.published_revision_id
                   WHERE template.archived_at IS NULL
                     AND template.template_kind = 'content_strategy'
                     AND revision.status = 'published'
                   ORDER BY template.template_code"""
            )
            templates = [dict(row) for row in c.fetchall()]
            c.execute(
                """SELECT asset_code, title, description, subject, usage, media_kind,
                          material_roles, execution_capability, rights_status, status
                   FROM assets
                   WHERE deleted_at IS NULL AND archived_at IS NULL
                   ORDER BY asset_code"""
            )
            assets = [dict(row) for row in c.fetchall()]
            subject_refs = [
                *(('content_strategy_template', row["template_code"]) for row in templates),
                *(('asset', row["asset_code"]) for row in assets),
                ("content_project", project_code),
            ]
            subject_types = [item[0] for item in subject_refs]
            subject_codes = [item[1] for item in subject_refs]
            c.execute(
                """SELECT effect_code, revision_number, subject_type, subject_code,
                          evidence_level, status, context, eligibility_snapshot
                   FROM functional_effect_estimates
                   WHERE subject_type = ANY(%s) AND subject_code = ANY(%s)
                   ORDER BY created_at DESC, effect_code DESC""",
                (subject_types, subject_codes),
            )
            effect_rows = [dict(row) for row in c.fetchall()]

        project_text = self._project_search_text(dict(project))
        effects_by_subject: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in effect_rows:
            effects_by_subject.setdefault(
                (str(row["subject_type"]), str(row["subject_code"])), []
            ).append(row)
        candidates = [
            self._template_recommendation(
                row,
                project_text,
                effects_by_subject.get(("content_strategy_template", row["template_code"]), [])
                or effects_by_subject.get(("template", row["template_code"]), []),
            )
            for row in templates
        ]
        candidates.extend(
            self._material_recommendation(
                row,
                project_text,
                effects_by_subject.get(("asset", row["asset_code"]), []),
            )
            for row in assets
        )
        candidates.sort(
            key=lambda item: (
                not item["constraint_eligible"],
                -item["total_score"],
                item["candidate_code"],
            )
        )
        return {
            "project_code": project_code,
            "project_revision_number": int(project["revision_number"]),
            "project_fingerprint_sha256": project["fingerprint_sha256"],
            "strategy_version": RECOMMENDATION_STRATEGY_VERSION,
            "recommendation_mode": "advisory_only",
            "candidates": candidates[:20],
            "project_effect_hints": self._effect_evidence(
                effects_by_subject.get(("content_project", project_code), [])
            ),
        }

    def approve_effect_estimate(self, effect_code: str, actor: str) -> dict[str, Any] | None:
        try:
            with self.connection.cursor(row_factory=dict_row) as c:
                c.execute(
                    "SELECT * FROM functional_effect_estimates WHERE effect_code = %s FOR UPDATE",
                    (effect_code,),
                )
                row = c.fetchone()
                if row is None:
                    self.connection.rollback()
                    return None
                if row["status"] == "revoked":
                    raise DomainValidationError(
                        "EFFECT_ESTIMATE_REVOKED",
                        "A revoked effect estimate cannot be approved",
                    )
                if row["status"] == "approved":
                    result = dict(row)
                elif row["status"] == "candidate":
                    c.execute(
                        """UPDATE functional_effect_estimates
                           SET status = 'approved', approved_by = %s, approved_at = now()
                           WHERE id = %s RETURNING *""",
                        (actor.strip(), row["id"]),
                    )
                    result = dict(c.fetchone())
                else:
                    raise DomainValidationError(
                        "EFFECT_ESTIMATE_NOT_APPROVABLE",
                        "Only a candidate effect estimate can be approved",
                        details={"effect_code": effect_code, "status": row["status"]},
                    )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return result

    def revoke_effect_estimate(
        self, effect_code: str, actor: str, reason: str
    ) -> dict[str, Any] | None:
        """Stop future use of an effect without modifying projects already reproduced from it."""
        try:
            with self.connection.cursor(row_factory=dict_row) as c:
                c.execute(
                    "SELECT * FROM functional_effect_estimates WHERE effect_code = %s FOR UPDATE",
                    (effect_code,),
                )
                row = c.fetchone()
                if row is None:
                    self.connection.rollback()
                    return None
                if row["status"] == "revoked":
                    result = dict(row)
                elif row["status"] in {"candidate", "approved"}:
                    c.execute(
                        """UPDATE functional_effect_estimates
                           SET status = 'revoked', revoked_by = %s, revoked_at = now(),
                               revoked_reason = %s
                           WHERE id = %s RETURNING *""",
                        (actor.strip(), reason.strip(), row["id"]),
                    )
                    result = dict(c.fetchone())
                else:
                    raise DomainValidationError(
                        "EFFECT_ESTIMATE_NOT_REVOCABLE",
                        "Only a candidate or approved effect estimate can be revoked",
                        details={"effect_code": effect_code, "status": row["status"]},
                    )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return result

    def reproduce_effect(self, effect_code: str, p: dict[str, Any]) -> dict[str, Any] | None:
        """Create a new content chain and non-executable production revision from an approved effect."""
        change_hypothesis = str(p.get("change_hypothesis") or "").strip()
        if not change_hypothesis:
            raise DomainValidationError(
                "EFFECT_REPRODUCTION_HYPOTHESIS_REQUIRED",
                "A reproduction requires a change hypothesis",
            )
        try:
            with self.connection.cursor(row_factory=dict_row) as c:
                c.execute(
                    "SELECT * FROM functional_effect_estimates WHERE effect_code = %s FOR UPDATE",
                    (effect_code,),
                )
                effect = c.fetchone()
                if effect is None:
                    self.connection.rollback()
                    return None
                if effect["status"] != "approved":
                    raise DomainValidationError(
                        "EFFECT_ESTIMATE_APPROVAL_REQUIRED",
                        "An effect estimate must be approved before it can seed a reproduction",
                        details={"effect_code": effect_code, "status": effect["status"]},
                    )
                if effect["subject_type"] != "content_project":
                    raise DomainValidationError(
                        "EFFECT_REPRODUCTION_SUBJECT_UNSUPPORTED",
                        "Only content-project effects can create a reproduction draft",
                        details={"subject_type": effect["subject_type"]},
                    )
                snapshot = (effect["effect_payload"] or {}).get("subject_snapshot")
                if not isinstance(snapshot, dict) or not isinstance(snapshot.get("content"), dict):
                    raise DomainValidationError(
                        "EFFECT_REPRODUCTION_SNAPSHOT_MISSING",
                        "The effect estimate does not contain a reproducible content-project snapshot",
                        details={"effect_code": effect_code},
                    )
                content, applied_choices, source_variant, selected_assets = (
                    self._apply_reproduction_choices(c, snapshot, p)
                )
                source_refs = list(snapshot.get("source_revision_refs") or [])
                decision_code = self._next(c, "DEC", "functional_decision_log")
                source_refs.extend(
                    [
                        {
                            "object_type": "content_project",
                            "project_code": snapshot["project_code"],
                            "revision": snapshot["revision_number"],
                            "fingerprint_sha256": snapshot["fingerprint_sha256"],
                            "relation_type": "reproduction_source",
                        },
                        {
                            "object_type": "effect_estimate",
                            "effect_code": effect["effect_code"],
                            "revision": effect["revision_number"],
                            "fingerprint_sha256": effect["fingerprint_sha256"],
                            "relation_type": "approved_effect",
                        },
                        {
                            "object_type": "decision_log",
                            "decision_code": decision_code,
                            "relation_type": "reproduction_decision",
                        },
                    ]
                )
                title = str(p.get("title") or f"{snapshot['title']} reproduction")
                generation_goal = str(p.get("generation_goal") or snapshot["generation_goal"])
                actor = str(p.get("actor") or "functional-operator").strip()
            created = ContentCoreRepository(self.connection).create_project(
                title=title,
                generation_goal=generation_goal,
                content=content,
                actor_id=actor,
                producer_strategy_revision="effect-reproduction.v2",
                source_revision_refs=source_refs,
                commit=False,
            )
            content_service = FunctionalContentService(self.connection)
            content_service.confirm_project(
                created["project_code"],
                expected_revision=int(created["revision_number"]),
                actor_id=actor,
            )
            content_service.parse_design_brief(
                created["project_code"],
                expected_revision=int(created["revision_number"]),
                raw_input=(
                    f"基于效果 {effect['effect_code']} 再生成。变更假设：{change_hypothesis}。"
                    f"人工保留/替换选择：{json.dumps(applied_choices, ensure_ascii=False, sort_keys=True)}"
                ),
                actor_id=actor,
            )
            content_service.confirm_design_brief(
                created["project_code"],
                expected_revision=int(created["revision_number"]),
                actor_id=actor,
            )
            generated = content_service.generate_chain(
                created["project_code"], actor_id=actor
            )
            generated = self._apply_generated_script_choices(
                content_service,
                generated,
                snapshot,
                list(p.get("paragraph_choices") or []),
                actor,
            )
            reproduced_project = ContentCoreRepository(self.connection).get_project(
                created["project_code"]
            )
            if reproduced_project is None:
                raise DomainValidationError(
                    "EFFECT_REPRODUCTION_PROJECT_MISSING",
                    "The reproduced content-project revision could not be reloaded",
                    details={"project_code": created["project_code"]},
                )
            carrier_kind = str((source_variant or {}).get("carrier_kind") or "live_room")
            variant = ContentProductionRepository(self.connection).create_production_variant(
                project_code=created["project_code"],
                project_revision=int(generated["revision_number"]),
                story_brief_code=generated["story_brief"]["story_brief_code"],
                story_brief_revision=int(generated["story_brief"]["revision_number"]),
                script_revision_code=generated["script"]["script_revision_code"],
                shot_list_revision_code=generated["shot_list"]["shot_list_revision_code"],
                carrier_kind=carrier_kind,
                branch_target={
                    "effect_reproduction": True,
                    "source_effect_code": effect["effect_code"],
                    "source_variant_code": (source_variant or {}).get("variant_code"),
                },
                configuration={
                    **dict((source_variant or {}).get("configuration") or {}),
                    "effect_reproduction": {
                        "effect_code": effect["effect_code"],
                        "change_hypothesis": change_hypothesis,
                        "applied_choices": applied_choices,
                    },
                },
                material_snapshot_ref={
                    "schema_version": "effect-reproduction-materials.v1",
                    "source_variant_code": (source_variant or {}).get("variant_code"),
                    "asset_codes": [item["asset_code"] for item in selected_assets],
                    "assets": selected_assets,
                },
                constraint_snapshot_ref={
                    "schema_version": "effect-reproduction-constraints.v1",
                    "source_variant_code": (source_variant or {}).get("variant_code"),
                    "recompute_required": True,
                },
                actor_id=actor,
                producer_strategy_revision="effect-reproduction.v2",
            )
            with self.connection.cursor(row_factory=dict_row) as c:
                decision = self._insert_decision(
                    c,
                    {
                        "project_code": created["project_code"],
                        "attribution_report_code": effect["attribution_report_code"],
                        "observation": f"Approved effect {effect['effect_code']} seeded a new draft.",
                        "recommendation": "Evaluate this reproduction independently before any release.",
                        "decision_type": "effect_reproduction",
                        "decision_payload": {
                            "change_hypothesis": change_hypothesis,
                            "source_project_code": snapshot["project_code"],
                            "source_project_revision_number": int(snapshot["revision_number"]),
                            "source_project_fingerprint_sha256": snapshot["fingerprint_sha256"],
                            "effect_code": effect["effect_code"],
                            "effect_revision_number": int(effect["revision_number"]),
                            "effect_fingerprint_sha256": effect["fingerprint_sha256"],
                            "applied_choices": applied_choices,
                            "reproduced_project_code": created["project_code"],
                            "reproduced_project_revision_number": int(
                                reproduced_project["revision_number"]
                            ),
                            "reproduced_project_fingerprint_sha256": reproduced_project[
                                "fingerprint_sha256"
                            ],
                            "production_variant_code": variant["variant_code"],
                            "production_variant_revision_number": int(variant["revision_number"]),
                            "production_variant_fingerprint_sha256": variant["fingerprint_sha256"],
                        },
                        "source_revision_refs": [
                            {
                                "object_type": "content_project",
                                "project_code": snapshot["project_code"],
                                "revision": int(snapshot["revision_number"]),
                                "fingerprint_sha256": snapshot["fingerprint_sha256"],
                                "relation_type": "reproduction_source",
                            },
                            {
                                "object_type": "effect_estimate",
                                "effect_code": effect["effect_code"],
                                "revision": int(effect["revision_number"]),
                                "fingerprint_sha256": effect["fingerprint_sha256"],
                                "relation_type": "approved_effect",
                            },
                            {
                                "object_type": "content_project",
                                "project_code": created["project_code"],
                                "revision": int(reproduced_project["revision_number"]),
                                "fingerprint_sha256": reproduced_project["fingerprint_sha256"],
                                "relation_type": "reproduction_result",
                            },
                            {
                                "object_type": "production_variant",
                                "variant_code": variant["variant_code"],
                                "revision": int(variant["revision_number"]),
                                "fingerprint_sha256": variant["fingerprint_sha256"],
                                "relation_type": "reproduction_result",
                            },
                        ],
                    },
                    decision_code=decision_code,
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return {
            "effect_code": effect["effect_code"],
            "decision_code": decision["decision_code"],
            "source_project_code": snapshot["project_code"],
            "source_project_revision_number": int(snapshot["revision_number"]),
            "reproduced_project_code": created["project_code"],
            "reproduced_project_revision_number": int(reproduced_project["revision_number"]),
            "production_variant_code": variant["variant_code"],
            "production_variant_revision_number": int(variant["revision_number"]),
            "applied_choices": applied_choices,
        }

    def create_experiment(self, p: dict[str, Any]) -> dict[str, Any]:
        variants = list(dict.fromkeys(p["variants"]))
        if len(variants) != 2:
            raise DomainValidationError(
                "EXPERIMENT_VARIANTS_INVALID",
                "Exactly two unique variants are required",
            )
        with self.connection.cursor(row_factory=dict_row) as c:
            code = self._next(c, "EXP", "functional_experiment")
            assignment_strategy = "stable_hash_sha256_v1"
            registration = dict(p["registration"])
            registration_fingerprint = canonical_fingerprint(
                {
                    "experiment_code": code,
                    "title": p["title"],
                    "metric_key": p["metric_key"],
                    "variants": variants,
                    "assignment_strategy": assignment_strategy,
                    "registration": registration,
                }
            )
            c.execute(
                """INSERT INTO functional_experiments
                   (experiment_code,title,metric_key,variants,registration,assignment_strategy,
                    registration_fingerprint_sha256)
                   VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (
                    code,
                    p["title"],
                    p["metric_key"],
                    Jsonb(variants),
                    Jsonb(registration),
                    assignment_strategy,
                    registration_fingerprint,
                ),
            )
            row = c.fetchone()
        self.connection.commit()
        return self._experiment(dict(row))

    def record_outcome(self, code: str, p: dict[str, Any]) -> dict[str, Any] | None:
        try:
            with self.connection.cursor(row_factory=dict_row) as c:
                c.execute(
                    "SELECT 1 FROM functional_experiments WHERE experiment_code=%s", (code,)
                )
                if c.fetchone() is None:
                    self.connection.rollback()
                    return None
                c.execute(
                    """SELECT variant_key FROM functional_experiment_assignments
                       WHERE experiment_code=%s AND subject_key=%s FOR UPDATE""",
                    (code, p["subject_key"]),
                )
                assignment = c.fetchone()
                if assignment is None:
                    raise DomainValidationError(
                        "EXPERIMENT_ASSIGNMENT_REQUIRED",
                        "A persisted experiment assignment is required before recording an outcome",
                        details={"experiment_code": code, "subject_key": p["subject_key"]},
                    )
                c.execute(
                    "INSERT INTO functional_experiment_outcomes (experiment_code,subject_key,variant_key,metric_value) VALUES (%s,%s,%s,%s) ON CONFLICT (experiment_code,subject_key) DO UPDATE SET metric_value=EXCLUDED.metric_value RETURNING id",
                    (code, p["subject_key"], assignment["variant_key"], p["metric_value"]),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_experiment(code)

    def assign_experiment_subject(
        self, code: str, subject_key: str
    ) -> dict[str, Any] | None:
        try:
            with self.connection.cursor(row_factory=dict_row) as c:
                c.execute(
                    "SELECT * FROM functional_experiments WHERE experiment_code=%s FOR UPDATE",
                    (code,),
                )
                experiment = c.fetchone()
                if experiment is None:
                    self.connection.rollback()
                    return None
                c.execute(
                    """SELECT * FROM functional_experiment_assignments
                       WHERE experiment_code=%s AND subject_key=%s FOR UPDATE""",
                    (code, subject_key),
                )
                assignment = c.fetchone()
                if assignment is None:
                    assignment_code = self._next(c, "ASSIGN", "functional_experiment_assignment")
                    c.execute(
                        """INSERT INTO functional_experiment_assignments
                           (assignment_code,experiment_code,subject_key,variant_key,assignment_strategy,
                            registration_fingerprint_sha256)
                           VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
                        (
                            assignment_code,
                            code,
                            subject_key,
                            self._assigned_variant(experiment["variants"], subject_key),
                            experiment["assignment_strategy"],
                            experiment["registration_fingerprint_sha256"],
                        ),
                    )
                    assignment = c.fetchone()
                result = {
                    "assignment_code": assignment["assignment_code"],
                    "experiment_code": assignment["experiment_code"],
                    "subject_key": assignment["subject_key"],
                    "variant_key": assignment["variant_key"],
                    "assignment_strategy": assignment["assignment_strategy"],
                    "registration_fingerprint_sha256": assignment[
                        "registration_fingerprint_sha256"
                    ],
                    "assigned_at": assignment["assigned_at"],
                }
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return result

    def get_experiment(self, code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as c:
            c.execute(
                "SELECT * FROM functional_experiments WHERE experiment_code=%s", (code,)
            )
            row = c.fetchone()
        return self._experiment(dict(row)) if row else None

    def list_experiments(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as c:
            c.execute("SELECT * FROM functional_experiments ORDER BY created_at DESC")
            return [self._experiment(dict(x)) for x in c.fetchall()]

    @staticmethod
    def _project_search_text(project: dict[str, Any]) -> str:
        content = project.get("content") or {}
        return " ".join(
            [
                str(project.get("title") or ""),
                str(project.get("generation_goal") or ""),
                json.dumps(content, ensure_ascii=False, sort_keys=True),
            ]
        )

    @staticmethod
    def _search_units(value: str) -> set[str]:
        normalized = value.casefold()
        words = set(re.findall(r"[a-z0-9]+", normalized))
        chinese = re.findall(r"[\u3400-\u9fff]", normalized)
        words.update(chinese)
        words.update("".join(chinese[index : index + 2]) for index in range(len(chinese) - 1))
        return {item for item in words if item}

    @classmethod
    def _content_match(cls, project_text: str, candidate_text: str) -> tuple[float, list[str]]:
        project_units = cls._search_units(project_text)
        candidate_units = cls._search_units(candidate_text)
        overlap = sorted(project_units & candidate_units)
        if not project_units or not candidate_units:
            return 0.0, ["没有可比较的内容关键词"]
        score = min(1.0, len(overlap) / max(4, min(len(candidate_units), 16)))
        reasons = (
            [f"匹配关键词：{'、'.join(overlap[:8])}"]
            if overlap
            else ["未发现直接内容关键词重合"]
        )
        return round(score, 4), reasons

    @staticmethod
    def _effect_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        for row in rows:
            eligibility = row.get("eligibility_snapshot") or {}
            selected_count = max(0, int(eligibility.get("selected_session_count") or 0))
            blockers = list(eligibility.get("association_blockers") or [])
            if row.get("status") != "approved":
                blockers.append("EFFECT_NOT_APPROVED")
            if row.get("evidence_level") != "associational":
                blockers.append("EFFECT_EVIDENCE_NOT_ASSOCIATIONAL")
            if selected_count < MINIMUM_EFFECT_SESSION_COUNT:
                blockers.append("EFFECT_SAMPLE_SIZE_BELOW_MINIMUM")
            blockers = list(dict.fromkeys(str(item) for item in blockers))
            eligible = not blockers and bool(
                eligibility.get("recommendation_eligible", True)
            )
            raw_score = (row.get("context") or {}).get("recommendation_score", 0.5)
            try:
                contribution = max(0.0, min(1.0, float(raw_score))) if eligible else 0.0
            except (TypeError, ValueError):
                contribution = 0.5 if eligible else 0.0
            evidence.append(
                {
                    "effect_code": row["effect_code"],
                    "revision_number": int(row["revision_number"]),
                    "evidence_level": row["evidence_level"],
                    "status": row["status"],
                    "selected_session_count": selected_count,
                    "eligible": eligible,
                    "blockers": blockers,
                    "contribution": round(contribution, 4),
                }
            )
        return evidence

    @classmethod
    def _template_recommendation(
        cls,
        row: dict[str, Any],
        project_text: str,
        effects: list[dict[str, Any]],
    ) -> dict[str, Any]:
        constraint_score = 0.0
        constraint_reasons: list[str] = []
        if row["content_readiness"] == "ready":
            constraint_score += 0.5
            constraint_reasons.append("模板内容已就绪")
        else:
            constraint_reasons.append(f"内容状态：{row['content_readiness']}")
        if row["buildability"] == "executable":
            constraint_score += 0.25
            constraint_reasons.append("模板可直接构建")
        else:
            constraint_score += 0.1
            constraint_reasons.append("模板仅作内容参考")
        constraint_score += 0.25 * float(row.get("confidence") or 0)
        content_score, content_reasons = cls._content_match(
            project_text,
            " ".join(
                [
                    str(row.get("name") or ""),
                    str(row.get("description") or ""),
                    json.dumps(row.get("content_strategy") or {}, ensure_ascii=False),
                ]
            ),
        )
        effect_evidence = cls._effect_evidence(effects)
        effect_score = max(
            (item["contribution"] for item in effect_evidence if item["eligible"]),
            default=0.0,
        )
        effect_reasons = (
            ["合格关联效果信号已计入建议分"]
            if effect_score
            else ["无合格关联效果信号；效果分不计入"]
        )
        return {
            "candidate_type": "template",
            "candidate_code": row["template_code"],
            "revision_number": int(row["revision_number"]),
            "title": row["name"],
            "constraint_score": round(constraint_score, 4),
            "content_score": content_score,
            "effect_score": effect_score,
            "total_score": round(
                0.45 * constraint_score + 0.4 * content_score + 0.15 * effect_score,
                4,
            ),
            "constraint_reasons": constraint_reasons,
            "content_reasons": content_reasons,
            "effect_reasons": effect_reasons,
            "effect_evidence": effect_evidence,
            "constraint_eligible": row["content_readiness"] == "ready",
            "effect_signal_used": effect_score > 0,
            "recommendation_mode": "advisory_only",
        }

    @classmethod
    def _material_recommendation(
        cls,
        row: dict[str, Any],
        project_text: str,
        effects: list[dict[str, Any]],
    ) -> dict[str, Any]:
        constraint_score = 0.0
        constraint_reasons: list[str] = []
        rights_ok = row["rights_status"] == "approved"
        capability_ok = row["execution_capability"] not in {
            "unavailable",
            "unclassified",
        }
        roles = list(row.get("material_roles") or [])
        if rights_ok:
            constraint_score += 0.45
            constraint_reasons.append("素材使用状态已批准")
        else:
            constraint_reasons.append(f"素材使用状态：{row['rights_status']}")
        if capability_ok:
            constraint_score += 0.35
            constraint_reasons.append(f"执行能力：{row['execution_capability']}")
        else:
            constraint_reasons.append("执行能力未就绪")
        if roles:
            constraint_score += 0.2
            constraint_reasons.append(f"素材角色：{'、'.join(roles)}")
        else:
            constraint_reasons.append("素材角色未分类")
        content_score, content_reasons = cls._content_match(
            project_text,
            " ".join(
                [
                    str(row.get("title") or ""),
                    str(row.get("description") or ""),
                    str(row.get("subject") or ""),
                    str(row.get("usage") or ""),
                    " ".join(str(role) for role in roles),
                ]
            ),
        )
        effect_evidence = cls._effect_evidence(effects)
        effect_score = max(
            (item["contribution"] for item in effect_evidence if item["eligible"]),
            default=0.0,
        )
        effect_reasons = (
            ["合格关联效果信号已计入建议分"]
            if effect_score
            else ["低证据或小样本信号仅提示，效果分为 0"]
        )
        return {
            "candidate_type": "material",
            "candidate_code": row["asset_code"],
            "revision_number": None,
            "title": row.get("title") or row["asset_code"],
            "constraint_score": round(constraint_score, 4),
            "content_score": content_score,
            "effect_score": effect_score,
            "total_score": round(
                0.45 * constraint_score + 0.4 * content_score + 0.15 * effect_score,
                4,
            ),
            "constraint_reasons": constraint_reasons,
            "content_reasons": content_reasons,
            "effect_reasons": effect_reasons,
            "effect_evidence": effect_evidence,
            "constraint_eligible": rights_ok and capability_ok and bool(roles),
            "effect_signal_used": effect_score > 0,
            "recommendation_mode": "advisory_only",
        }

    @staticmethod
    def _template_codes(content: dict[str, Any]) -> list[str]:
        codes: list[str] = []
        primary = content.get("primary_template_ref") or {}
        if isinstance(primary, dict) and primary.get("template_code"):
            codes.append(str(primary["template_code"]))
        for item in content.get("secondary_template_refs") or []:
            if isinstance(item, dict) and item.get("template_code"):
                codes.append(str(item["template_code"]))
        return codes

    def _apply_reproduction_choices(
        self,
        cursor: Any,
        snapshot: dict[str, Any],
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
        content = json.loads(json.dumps(snapshot["content"], ensure_ascii=False))
        template_choices = [dict(item) for item in payload.get("template_choices") or []]
        paragraph_choices = [dict(item) for item in payload.get("paragraph_choices") or []]
        material_choices = [dict(item) for item in payload.get("material_choices") or []]
        source_template_codes = set(self._template_codes(content))
        applied_templates: list[dict[str, Any]] = []
        for choice in template_choices:
            source_code = str(choice["source_template_code"])
            if source_code not in source_template_codes:
                raise DomainValidationError(
                    "EFFECT_REPRODUCTION_TEMPLATE_SOURCE_INVALID",
                    "A template choice must reference the frozen source project",
                    details={"source_template_code": source_code},
                )
            if choice["action"] == "preserve":
                applied_templates.append(choice)
                continue
            replacement_code = str(choice["replacement_template_code"])
            cursor.execute(
                """SELECT template.template_code, revision.revision_number,
                          revision.content_fingerprint
                   FROM live_room_templates AS template
                   JOIN live_room_template_revisions AS revision
                     ON revision.id = template.published_revision_id
                   WHERE template.template_code = %s
                     AND template.archived_at IS NULL
                     AND revision.status = 'published'""",
                (replacement_code,),
            )
            replacement = cursor.fetchone()
            if replacement is None or (
                choice.get("replacement_revision") is not None
                and int(choice["replacement_revision"]) != int(replacement["revision_number"])
            ):
                raise DomainValidationError(
                    "EFFECT_REPRODUCTION_TEMPLATE_REPLACEMENT_INVALID",
                    "A replacement template must be the selected published revision",
                    details={"replacement_template_code": replacement_code},
                )
            primary = content.get("primary_template_ref") or {}
            replacement_ref = {
                "template_code": replacement_code,
                "revision": int(replacement["revision_number"]),
                "fingerprint_sha256": replacement["content_fingerprint"],
                "selection_role": (
                    primary.get("selection_role", "primary")
                    if isinstance(primary, dict) and primary.get("template_code") == source_code
                    else "secondary"
                ),
                "contribution": "effect_reproduction_replacement",
            }
            if isinstance(primary, dict) and primary.get("template_code") == source_code:
                content["primary_template_code"] = replacement_code
                content["primary_template_ref"] = replacement_ref
            else:
                secondary = [
                    replacement_ref
                    if isinstance(item, dict) and item.get("template_code") == source_code
                    else item
                    for item in content.get("secondary_template_refs") or []
                ]
                content["secondary_template_refs"] = secondary
                content["secondary_template_codes"] = [
                    str(item["template_code"])
                    for item in secondary
                    if isinstance(item, dict) and item.get("template_code")
                ]
            applied_templates.append(
                {**choice, "replacement_revision": int(replacement["revision_number"])}
            )

        applied_paragraphs: list[dict[str, Any]] = []
        source_block_codes = {
            str(item["block_code"])
            for item in snapshot.get("script_blocks") or []
            if isinstance(item, dict) and item.get("block_code")
        }
        for choice in paragraph_choices:
            field_key = choice.get("field_key")
            source_block_code = choice.get("source_block_code")
            if field_key:
                if field_key not in {"theme", "story", "detailed_design"}:
                    raise DomainValidationError(
                        "EFFECT_REPRODUCTION_PARAGRAPH_SOURCE_INVALID",
                        "The selected narrative field is not reproducible",
                    )
                if choice["action"] == "replace":
                    content[str(field_key)] = str(choice["replacement_text"])
            elif str(source_block_code) not in source_block_codes:
                raise DomainValidationError(
                    "EFFECT_REPRODUCTION_PARAGRAPH_SOURCE_INVALID",
                    "A paragraph choice must reference the frozen source script",
                    details={"source_block_code": source_block_code},
                )
            applied_paragraphs.append(choice)

        source_variants = [
            dict(item) for item in snapshot.get("production_variants") or []
            if isinstance(item, dict)
        ]
        source_variant = source_variants[0] if source_variants else None
        material_snapshot = dict((source_variant or {}).get("material_snapshot_ref") or {})
        source_asset_codes = [str(item) for item in material_snapshot.get("asset_codes") or []]
        choices_by_source = {
            str(item["source_asset_code"]): item for item in material_choices
        }
        unknown_materials = sorted(set(choices_by_source) - set(source_asset_codes))
        if unknown_materials:
            raise DomainValidationError(
                "EFFECT_REPRODUCTION_MATERIAL_SOURCE_INVALID",
                "A material choice must reference the frozen source production revision",
                details={"asset_codes": unknown_materials},
            )
        selected_asset_codes: list[str] = []
        applied_materials: list[dict[str, Any]] = []
        for source_code in source_asset_codes:
            choice = choices_by_source.get(source_code) or {
                "source_asset_code": source_code,
                "action": "preserve",
                "replacement_asset_code": None,
            }
            target_code = (
                str(choice["replacement_asset_code"])
                if choice["action"] == "replace"
                else source_code
            )
            if target_code not in selected_asset_codes:
                selected_asset_codes.append(target_code)
            applied_materials.append({**choice, "result_asset_code": target_code})
        selected_assets: list[dict[str, Any]] = []
        if selected_asset_codes:
            cursor.execute(
                """SELECT asset_code, media_kind, material_roles,
                          execution_capability, rights_status, checksum_sha256
                   FROM assets
                   WHERE asset_code = ANY(%s) AND deleted_at IS NULL AND archived_at IS NULL""",
                (selected_asset_codes,),
            )
            assets_by_code = {row["asset_code"]: dict(row) for row in cursor.fetchall()}
            invalid_assets = [
                code for code in selected_asset_codes
                if code not in assets_by_code
                or assets_by_code[code]["rights_status"] != "approved"
                or assets_by_code[code]["execution_capability"] in {"unavailable", "unclassified"}
            ]
            if invalid_assets:
                raise DomainValidationError(
                    "EFFECT_REPRODUCTION_MATERIAL_REPLACEMENT_INVALID",
                    "Reproduction materials must be active, rights-approved, and executable",
                    details={"asset_codes": invalid_assets},
                )
            selected_assets = [assets_by_code[code] for code in selected_asset_codes]

        applied_choices = {
            "schema_version": "effect-reproduction-choices.v1",
            "template_choices": applied_templates,
            "paragraph_choices": applied_paragraphs,
            "material_choices": applied_materials,
        }
        content["effect_reproduction_selection"] = applied_choices
        return content, applied_choices, source_variant, selected_assets

    @staticmethod
    def _apply_generated_script_choices(
        content_service: FunctionalContentService,
        generated: dict[str, Any],
        snapshot: dict[str, Any],
        paragraph_choices: list[dict[str, Any]],
        actor: str,
    ) -> dict[str, Any]:
        replacements = {
            str(choice["source_block_code"]): str(choice["replacement_text"])
            for choice in paragraph_choices
            if choice.get("source_block_code") and choice.get("action") == "replace"
        }
        if not replacements:
            return generated
        source_blocks = {
            str(item["block_code"]): item
            for item in snapshot.get("script_blocks") or []
            if isinstance(item, dict) and item.get("block_code")
        }
        generated_blocks = [dict(item) for item in generated["script"].get("blocks") or []]
        by_order = {int(item["sort_order"]): item for item in generated_blocks}
        for source_code, replacement_text in replacements.items():
            source = source_blocks[source_code]
            if source.get("fact_citations"):
                raise DomainValidationError(
                    "EFFECT_REPRODUCTION_FACT_PARAGRAPH_LOCKED",
                    "A paragraph with fact citations cannot be replaced without reviewing its citations",
                    details={"source_block_code": source_code},
                )
            target = by_order.get(int(source["sort_order"]))
            if target is None or target.get("fact_citations"):
                raise DomainValidationError(
                    "EFFECT_REPRODUCTION_PARAGRAPH_TARGET_MISSING",
                    "The generated script does not have an editable matching paragraph",
                    details={"source_block_code": source_code},
                )
            target["content"] = replacement_text
        return content_service.revise_script(
            generated["project_code"],
            expected_revision=int(generated["revision_number"]),
            blocks=[by_order[index] for index in sorted(by_order)],
            actor_id=actor,
        )

    def _experiment(self, row: dict[str, Any]) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as c:
            c.execute(
                "SELECT variant_key,avg(metric_value) average,count(*) sample_size FROM functional_experiment_outcomes WHERE experiment_code=%s GROUP BY variant_key",
                (row["experiment_code"],),
            )
            out = {
                x["variant_key"]: {
                    "average": float(x["average"]),
                    "sample_size": x["sample_size"],
                }
                for x in c.fetchall()
            }
        row["results"] = {
            v: out.get(v, {"average": 0.0, "sample_size": 0}) for v in row["variants"]
        }
        return row

    def _insert_decision(
        self, c: Any, p: dict[str, Any], *, decision_code: str | None = None
    ) -> dict[str, Any]:
        report_code = p.get("attribution_report_code")
        if report_code:
            c.execute(
                "SELECT report_code FROM functional_attribution_reports WHERE report_code = %s",
                (report_code,),
            )
            if c.fetchone() is None:
                raise DomainValidationError(
                    "LEARNING_ATTRIBUTION_REPORT_NOT_FOUND",
                    "The selected attribution report does not exist",
                    details={"attribution_report_code": report_code},
                )
        code = decision_code or self._next(c, "DEC", "functional_decision_log")
        decision_type = str(p.get("decision_type") or "manual_recommendation")
        payload = dict(p.get("decision_payload") or {})
        source_refs = list(p.get("source_revision_refs") or [])
        fingerprint = canonical_fingerprint(
            {
                "decision_code": code,
                "project_code": p.get("project_code"),
                "attribution_report_code": report_code,
                "observation": p["observation"],
                "recommendation": p["recommendation"],
                "decision_type": decision_type,
                "decision_payload": payload,
                "source_revision_refs": source_refs,
            }
        )
        c.execute(
            """INSERT INTO functional_decision_logs
               (decision_code,project_code,attribution_report_code,observation,recommendation,
                decision_type,decision_payload,source_revision_refs,fingerprint_sha256)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (
                code,
                p.get("project_code"),
                report_code,
                p["observation"],
                p["recommendation"],
                decision_type,
                Jsonb(payload),
                Jsonb(source_refs),
                fingerprint,
            ),
        )
        return dict(c.fetchone())

    @staticmethod
    def _assigned_variant(variants: list[str], subject_key: str) -> str:
        return variants[int(hashlib.sha256(subject_key.encode()).hexdigest(), 16) % len(variants)]

    @staticmethod
    def _subject_snapshot(c: Any, subject_type: str, subject_code: str) -> dict[str, Any] | None:
        if subject_type != "content_project":
            return None
        c.execute(
            """
            SELECT revision.id AS project_revision_id, project.id AS project_id,
                   revision.project_code, revision.revision_number, project.title,
                   revision.generation_goal, revision.content, revision.source_revision_refs,
                   revision.fingerprint_sha256
            FROM content_projects AS project
            JOIN content_project_revisions AS revision
              ON revision.project_id = project.id
             AND revision.revision_number = project.current_revision_number
            WHERE project.project_code = %s
            """,
            (subject_code,),
        )
        row = c.fetchone()
        if row is None:
            raise DomainValidationError(
                "EFFECT_ESTIMATE_SUBJECT_NOT_FOUND",
                "The selected content project does not exist",
                details={"subject_type": subject_type, "subject_code": subject_code},
            )
        snapshot = dict(row)
        c.execute(
            """SELECT variant.variant_code, variant.revision_number, variant.status,
                      variant.carrier_kind, variant.configuration,
                      variant.material_snapshot_ref, variant.constraint_snapshot_ref,
                      variant.fingerprint_sha256
               FROM production_variant_revisions AS variant
               WHERE variant.source_project_revision_id = %s
               ORDER BY CASE WHEN variant.carrier_kind = 'live_room' THEN 0 ELSE 1 END,
                        CASE WHEN variant.status = 'confirmed' THEN 0 ELSE 1 END,
                        variant.revision_number DESC""",
            (row["project_revision_id"],),
        )
        snapshot["production_variants"] = [dict(item) for item in c.fetchall()]
        c.execute(
            """SELECT block.block_code, block.sort_order, block.module_type,
                      block.content, block.estimated_duration_ms,
                      block.fact_citations, block.template_sources,
                      block.content_rule_refs, block.interaction_intent,
                      block.cta_intent, block.fingerprint_sha256
               FROM content_script_revisions AS script
               JOIN content_script_blocks AS block ON block.script_revision_id = script.id
               WHERE script.id = (
                   SELECT latest.id FROM content_script_revisions AS latest
                   WHERE latest.project_id = %s AND latest.status = 'confirmed'
                   ORDER BY latest.revision_number DESC LIMIT 1
               )
               ORDER BY block.sort_order""",
            (row["project_id"],),
        )
        snapshot["script_blocks"] = [dict(item) for item in c.fetchall()]
        snapshot.pop("project_revision_id", None)
        snapshot.pop("project_id", None)
        return snapshot

    @staticmethod
    def _next(c: Any, prefix: str, kind: str) -> str:
        date = datetime.now(UTC).date()
        c.execute(
            "INSERT INTO domain_sequences(sequence_date,object_type,current_value) VALUES(%s,%s,1) ON CONFLICT(sequence_date,object_type) DO UPDATE SET current_value=domain_sequences.current_value+1 RETURNING current_value",
            (date, kind),
        )
        return f"{prefix}-{date:%Y%m%d}-{int(c.fetchone()['current_value']):06d}"
