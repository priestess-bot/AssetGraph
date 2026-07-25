from __future__ import annotations
import hashlib
from datetime import UTC, datetime
from typing import Any
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from app.domain.contracts import canonical_fingerprint
from app.domain.errors import DomainValidationError
from app.repositories.content_core import ContentCoreRepository


class FunctionalLearningService:
    def __init__(self, connection: Connection):
        self.connection = connection

    def create_decision(self, p: dict[str, Any]) -> dict[str, Any]:
        try:
            with self.connection.cursor(row_factory=dict_row) as c:
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
                code = self._next(c, "DEC", "functional_decision_log")
                c.execute(
                    "INSERT INTO functional_decision_logs (decision_code,project_code,attribution_report_code,observation,recommendation) VALUES (%s,%s,%s,%s,%s) RETURNING *",
                    (
                        code,
                        p.get("project_code"),
                        report_code,
                        p["observation"],
                        p["recommendation"],
                    ),
                )
                row = c.fetchone()
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return dict(row)

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
                eligibility = {
                    "report_code": report["report_code"],
                    "report_created_at": report["created_at"].isoformat(),
                    "evidence_level": report["evidence_level"],
                    "selected_session_count": metadata.get("selected_session_count", 0),
                    "observed_session_count": metadata.get("observed_session_count", 0),
                    "metric_definition_state": metadata.get("metric_definition_state", "metric_unpinned"),
                    "has_groups": bool(groups),
                    "qualification": "descriptive_only",
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
                       VALUES (%s,1,%s,%s,%s,%s,'descriptive','candidate',%s,%s,%s,%s,%s)
                       RETURNING *""",
                    (
                        effect_code,
                        report["report_code"],
                        p["subject_type"],
                        p["subject_code"],
                        report["metric_key"],
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
        """Create a fresh draft from the immutable content-project snapshot on an approved effect."""
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
                source_refs = list(snapshot.get("source_revision_refs") or [])
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
                    ]
                )
                title = str(p.get("title") or f"{snapshot['title']} reproduction")
                generation_goal = str(p.get("generation_goal") or snapshot["generation_goal"])
            created = ContentCoreRepository(self.connection).create_project(
                title=title,
                generation_goal=generation_goal,
                content=dict(snapshot["content"]),
                actor_id="functional-operator",
                producer_strategy_revision="effect-reproduction.v1",
                source_revision_refs=source_refs,
            )
        except Exception:
            self.connection.rollback()
            raise
        return {
            "effect_code": effect["effect_code"],
            "source_project_code": snapshot["project_code"],
            "source_project_revision_number": int(snapshot["revision_number"]),
            "reproduced_project_code": created["project_code"],
            "reproduced_project_revision_number": int(created["revision_number"]),
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
        with self.connection.cursor(row_factory=dict_row) as c:
            c.execute(
                "SELECT * FROM functional_experiments WHERE experiment_code=%s", (code,)
            )
            e = c.fetchone()
            if not e:
                self.connection.rollback()
                return None
            variant = self._assigned_variant(e["variants"], p["subject_key"])
            c.execute(
                "INSERT INTO functional_experiment_outcomes (experiment_code,subject_key,variant_key,metric_value) VALUES (%s,%s,%s,%s) ON CONFLICT (experiment_code,subject_key) DO UPDATE SET metric_value=EXCLUDED.metric_value RETURNING id",
                (code, p["subject_key"], variant, p["metric_value"]),
            )
        self.connection.commit()
        return self.get_experiment(code)

    def get_experiment_assignment(
        self, code: str, subject_key: str
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as c:
            c.execute(
                """SELECT experiment_code, variants, assignment_strategy,
                          registration_fingerprint_sha256
                   FROM functional_experiments WHERE experiment_code=%s""",
                (code,),
            )
            row = c.fetchone()
        if row is None:
            return None
        return {
            "experiment_code": row["experiment_code"],
            "subject_key": subject_key,
            "variant_key": self._assigned_variant(row["variants"], subject_key),
            "assignment_strategy": row["assignment_strategy"],
            "registration_fingerprint_sha256": row["registration_fingerprint_sha256"],
        }

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

    @staticmethod
    def _assigned_variant(variants: list[str], subject_key: str) -> str:
        return variants[int(hashlib.sha256(subject_key.encode()).hexdigest(), 16) % len(variants)]

    @staticmethod
    def _subject_snapshot(c: Any, subject_type: str, subject_code: str) -> dict[str, Any] | None:
        if subject_type != "content_project":
            return None
        c.execute(
            """
            SELECT revision.project_code, revision.revision_number, project.title,
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
        return dict(row)

    @staticmethod
    def _next(c: Any, prefix: str, kind: str) -> str:
        date = datetime.now(UTC).date()
        c.execute(
            "INSERT INTO domain_sequences(sequence_date,object_type,current_value) VALUES(%s,%s,1) ON CONFLICT(sequence_date,object_type) DO UPDATE SET current_value=domain_sequences.current_value+1 RETURNING current_value",
            (date, kind),
        )
        return f"{prefix}-{date:%Y%m%d}-{int(c.fetchone()['current_value']):06d}"
