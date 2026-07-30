from __future__ import annotations
import os
from uuid import uuid4
import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.errors import DomainValidationError
from app.services.functional_content import FunctionalContentService
from app.services.functional_learning import FunctionalLearningService

DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured"
)


def _registration() -> dict[str, object]:
    return {
        "hypothesis": "A concise opening improves watcher count.",
        "treatment_mechanism": "Use the approved concise opening in the treatment variant.",
        "estimand": "Mean watcher-count difference between assigned variants.",
        "inclusion_rules": "Include eligible sessions during the stated window.",
        "observation_window": "2026-07-25T00:00:00Z/2026-07-26T00:00:00Z",
        "covariates": ["weekday"],
        "identification_assumptions": "Stable assignment and no cross-variant interference.",
        "analysis_plan": "Report descriptive per-variant averages only.",
    }


def test_decisions_and_stable_experiment_outcomes() -> None:
    with psycopg.connect(DATABASE_URL) as c:
        s = FunctionalLearningService(c)
        source = FunctionalContentService(c).create_project(
            {
                "title": f"Effect source {uuid4().hex}",
                "generation_goal": "Explain a product choice",
                "platform": "douyin",
            },
            actor_id="test-operator",
        )
        report_code = f"ATTR-LEARNING-{uuid4().hex}"
        with c.cursor() as cursor:
            cursor.execute(
                """INSERT INTO functional_attribution_reports
                   (report_code, metric_key, session_codes, results)
                   VALUES (%s, %s, %s, %s)""",
                (
                    report_code,
                    "watchers",
                    Jsonb(["OPS-001"]),
                    Jsonb({"groups": {}, "metadata": {}}),
                ),
            )
        c.commit()
        d = s.create_decision(
            {
                "observation": "观看人数较高",
                "recommendation": "复用开场节奏",
                "attribution_report_code": report_code,
            }
        )
        assert d["decision_code"].startswith("DEC-")
        assert d["attribution_report_code"] == report_code
        effect = s.create_effect_estimate(
            {
                "attribution_report_code": report_code,
                "subject_type": "content_project",
                "subject_code": source["project_code"],
                "context": {"platform": "douyin"},
                "note": "Manual review of this descriptive report.",
            }
        )
        assert effect["status"] == "candidate"
        assert effect["eligibility_snapshot"]["qualification"] == "descriptive_hint_only"
        assert effect["eligibility_snapshot"]["recommendation_eligible"] is False
        approved = s.approve_effect_estimate(effect["effect_code"], "operator")
        assert approved is not None
        assert approved["status"] == "approved"
        reproduction = s.reproduce_effect(
            effect["effect_code"],
            {
                "title": "Reproduced effect project",
                "change_hypothesis": "Keep the approved opening while evaluating a new draft.",
            },
        )
        assert reproduction is not None
        assert reproduction["decision_code"].startswith("DEC-")
        assert reproduction["source_project_code"] == source["project_code"]
        assert reproduction["reproduced_project_code"] != source["project_code"]
        assert reproduction["production_variant_code"].startswith("VARIANT-")
        with c.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT source_revision_refs FROM content_project_revisions WHERE project_code = %s",
                (reproduction["reproduced_project_code"],),
            )
            reproduced_refs = cursor.fetchone()["source_revision_refs"]
        assert any(ref["relation_type"] == "approved_effect" for ref in reproduced_refs)
        assert any(ref["relation_type"] == "reproduction_decision" for ref in reproduced_refs)
        with c.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM functional_decision_logs WHERE decision_code = %s",
                (reproduction["decision_code"],),
            )
            reproduction_decision = cursor.fetchone()
        assert reproduction_decision["decision_type"] == "effect_reproduction"
        assert reproduction_decision["decision_payload"]["reproduced_project_code"] == reproduction[
            "reproduced_project_code"
        ]
        with c.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT status, branch_target, configuration
                   FROM production_variant_revisions
                   WHERE variant_code = %s AND revision_number = %s""",
                (
                    reproduction["production_variant_code"],
                    reproduction["production_variant_revision_number"],
                ),
            )
            reproduction_variant = cursor.fetchone()
        assert reproduction_variant["status"] == "draft"
        assert reproduction_variant["branch_target"]["effect_reproduction"] is True
        revoked = s.revoke_effect_estimate(
            effect["effect_code"],
            "operator",
            "The supporting metric input was corrected.",
        )
        assert revoked is not None
        assert revoked["status"] == "revoked"
        assert revoked["revoked_by"] == "operator"
        assert revoked["revoked_reason"] == "The supporting metric input was corrected."
        with pytest.raises(DomainValidationError) as revoked_reproduction:
            s.reproduce_effect(
                effect["effect_code"],
                {"change_hypothesis": "This must not run after the effect is revoked."},
            )
        assert revoked_reproduction.value.code == "EFFECT_ESTIMATE_APPROVAL_REQUIRED"
        repeated_revocation = s.revoke_effect_estimate(
            effect["effect_code"],
            "another-operator",
            "This must not overwrite the original reason.",
        )
        assert repeated_revocation is not None
        assert repeated_revocation["revoked_by"] == "operator"
        with pytest.raises(DomainValidationError) as missing_report:
            s.create_decision(
                {
                    "observation": "不存在的归因报告",
                    "recommendation": "不得关联",
                    "attribution_report_code": "ATTR-MISSING",
                }
            )
        assert missing_report.value.code == "LEARNING_ATTRIBUTION_REPORT_NOT_FOUND"
        e = s.create_experiment(
            {
                "title": "Opening",
                "metric_key": "watchers",
                "variants": ["control", "treatment"],
                "registration": _registration(),
            }
        )
        assert e["registration"]["hypothesis"] == _registration()["hypothesis"]
        assert e["registration_fingerprint_sha256"]
        with pytest.raises(DomainValidationError) as missing_assignment:
            s.record_outcome(
                e["experiment_code"], {"subject_key": "viewer-1", "metric_value": 12}
            )
        assert missing_assignment.value.code == "EXPERIMENT_ASSIGNMENT_REQUIRED"
        assignment = s.assign_experiment_subject(e["experiment_code"], "viewer-1")
        assert assignment is not None
        assert assignment["assignment_code"].startswith("ASSIGN-")
        assert assignment["assignment_strategy"] == "stable_hash_sha256_v1"
        first = s.record_outcome(
            e["experiment_code"], {"subject_key": "viewer-1", "metric_value": 12}
        )
        second = s.record_outcome(
            e["experiment_code"], {"subject_key": "viewer-1", "metric_value": 20}
        )
        assert first and second
        assert sum(item["sample_size"] for item in second["results"].values()) == 1
        assert assignment["variant_key"] in second["results"]
