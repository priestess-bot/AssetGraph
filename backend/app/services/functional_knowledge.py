from __future__ import annotations
from datetime import UTC, datetime
from typing import Any
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.contracts import canonical_fingerprint


class FunctionalKnowledgeConflictError(RuntimeError):
    pass


class FunctionalKnowledgeService:
    def __init__(self, c: Connection):
        self.c = c

    def create(self, p: dict[str, Any]) -> dict[str, Any]:
        try:
            with self.c.cursor(row_factory=dict_row) as cur:
                code = self._next(cur, "functional_knowledge_fact", "FACT")
                cur.execute(
                    "INSERT INTO functional_knowledge_facts(fact_code,title,claim,source_url,related_codes) VALUES(%s,%s,%s,%s,%s) RETURNING *",
                    (
                        code,
                        p["title"],
                        p["claim"],
                        p.get("source_url"),
                        Jsonb(list(dict.fromkeys(p.get("related_codes") or []))),
                    ),
                )
                row = cur.fetchone()
            self.c.commit()
        except Exception:
            self.c.rollback()
            raise
        return dict(row)

    def list(self, q: str | None = None) -> list[dict[str, Any]]:
        with self.c.cursor(row_factory=dict_row) as cur:
            if q:
                pattern = f"%{q}%"
                cur.execute(
                    "SELECT * FROM functional_knowledge_facts WHERE status='approved' AND (title ILIKE %s OR claim ILIKE %s) ORDER BY created_at DESC",
                    (pattern, pattern),
                )
            else:
                cur.execute(
                    "SELECT * FROM functional_knowledge_facts WHERE status='approved' ORDER BY created_at DESC"
                )
            return [dict(x) for x in cur.fetchall()]

    def impact(self, code: str) -> list[dict[str, Any]]:
        with self.c.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM functional_knowledge_facts WHERE fact_code=%s OR related_codes ? %s ORDER BY created_at DESC",
                (code, code),
            )
            return [dict(x) for x in cur.fetchall()]

    def create_source_evidence(self, payload: dict[str, Any]) -> dict[str, Any]:
        fingerprint_input = {
            "source_type": payload["source_type"],
            "title": payload["title"],
            "source_url": payload.get("source_url"),
            "excerpt": payload["excerpt"],
            "captured_at": payload.get("captured_at"),
            "access_scope": payload["access_scope"],
        }
        checksum = canonical_fingerprint(fingerprint_input)
        try:
            with self.c.cursor(row_factory=dict_row) as cur:
                code = self._next(cur, "functional_knowledge_source_evidence", "EVIDENCE")
                cur.execute(
                    """INSERT INTO functional_knowledge_source_evidences
                       (evidence_code,source_type,title,source_url,excerpt,content_sha256,captured_at,access_scope,created_by)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (
                        code,
                        payload["source_type"],
                        payload["title"],
                        payload.get("source_url"),
                        payload["excerpt"],
                        checksum,
                        payload.get("captured_at"),
                        payload["access_scope"],
                        payload.get("created_by"),
                    ),
                )
                row = cur.fetchone()
            self.c.commit()
        except Exception:
            self.c.rollback()
            raise
        return dict(row)

    def list_source_evidences(self) -> list[dict[str, Any]]:
        with self.c.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM functional_knowledge_source_evidences ORDER BY created_at DESC, evidence_code DESC"
            )
            return [dict(row) for row in cur.fetchall()]

    def create_content_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with self.c.cursor(row_factory=dict_row) as cur:
                self._require_approved_rule_source(cur, payload.get("source_evidence_code"))
                code = self._next(cur, "functional_knowledge_content_rule", "RULE")
                fingerprint = canonical_fingerprint(
                    {
                        "rule_kind": payload["rule_kind"],
                        "directive": payload["directive"],
                        "title": payload["title"],
                        "rule_text": payload["rule_text"],
                        "scope": payload.get("scope") or {},
                        "source_evidence_code": payload.get("source_evidence_code"),
                        "valid_from": payload.get("valid_from"),
                        "valid_until": payload.get("valid_until"),
                    }
                )
                cur.execute(
                    """
                    INSERT INTO functional_knowledge_content_rules (
                        rule_code, rule_kind, directive, title, rule_text, scope,
                        source_evidence_code, valid_from, valid_until, created_by,
                        fingerprint_sha256
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        code,
                        payload["rule_kind"],
                        payload["directive"],
                        payload["title"].strip(),
                        payload["rule_text"].strip(),
                        Jsonb(payload.get("scope") or {}),
                        payload.get("source_evidence_code"),
                        payload.get("valid_from"),
                        payload.get("valid_until"),
                        payload.get("created_by"),
                        fingerprint,
                    ),
                )
                row = self._content_rule(cur, code)
            self.c.commit()
        except Exception:
            self.c.rollback()
            raise
        if row is None:
            raise RuntimeError("created content rule could not be read")
        return row

    def list_content_rules(self, q: str | None = None) -> list[dict[str, Any]]:
        with self.c.cursor(row_factory=dict_row) as cur:
            if q and q.strip():
                pattern = f"%{q.strip()}%"
                cur.execute(
                    self._content_rule_query(
                        "WHERE rule.title ILIKE %s OR rule.rule_text ILIKE %s OR rule.rule_code ILIKE %s"
                    ),
                    (pattern, pattern, pattern),
                )
            else:
                cur.execute(self._content_rule_query())
            return [dict(row) for row in cur.fetchall()]

    def resolve_approved_content_rule(self, rule_code: str) -> dict[str, Any] | None:
        with self.c.cursor(row_factory=dict_row) as cur:
            cur.execute(
                self._content_rule_query(
                    "WHERE rule.rule_code = %s AND rule.status = 'approved' "
                    "AND (rule.source_evidence_code IS NULL OR source.status = 'approved')"
                ),
                (rule_code,),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def approve_content_rule(self, rule_code: str, approved_by: str) -> dict[str, Any] | None:
        try:
            with self.c.cursor(row_factory=dict_row) as cur:
                rule = self._content_rule(cur, rule_code, lock=True)
                if rule is None:
                    self.c.rollback()
                    return None
                if rule["status"] == "approved":
                    self.c.commit()
                    return rule
                if rule["status"] != "draft":
                    raise FunctionalKnowledgeConflictError("Only draft content rules can be approved")
                self._require_approved_rule_source(cur, rule.get("source_evidence_code"))
                cur.execute(
                    """
                    UPDATE functional_knowledge_content_rules
                    SET status = 'approved', approved_by = %s, approved_at = now(), updated_at = now()
                    WHERE rule_code = %s
                    """,
                    (approved_by.strip(), rule_code),
                )
                result = self._content_rule(cur, rule_code)
            self.c.commit()
        except Exception:
            self.c.rollback()
            raise
        return result

    def reject_content_rule(
        self, rule_code: str, actor: str, reason: str
    ) -> dict[str, Any] | None:
        try:
            with self.c.cursor(row_factory=dict_row) as cur:
                rule = self._content_rule(cur, rule_code, lock=True)
                if rule is None:
                    self.c.rollback()
                    return None
                if rule["status"] == "rejected":
                    result = rule
                elif rule["status"] == "draft":
                    cur.execute(
                        """
                        UPDATE functional_knowledge_content_rules
                        SET status = 'rejected', rejected_by = %s, rejected_at = now(),
                            rejection_reason = %s, updated_at = now()
                        WHERE rule_code = %s
                        """,
                        (actor.strip(), reason.strip(), rule_code),
                    )
                    result = self._content_rule(cur, rule_code)
                else:
                    raise FunctionalKnowledgeConflictError("Only draft content rules can be rejected")
            self.c.commit()
        except Exception:
            self.c.rollback()
            raise
        return result

    def revoke_content_rule(
        self, rule_code: str, actor: str, reason: str
    ) -> dict[str, Any] | None:
        try:
            with self.c.cursor(row_factory=dict_row) as cur:
                rule = self._content_rule(cur, rule_code, lock=True)
                if rule is None:
                    self.c.rollback()
                    return None
                if rule["status"] == "revoked":
                    result = rule
                elif rule["status"] == "approved":
                    cur.execute(
                        """
                        UPDATE functional_knowledge_content_rules
                        SET status = 'revoked', revoked_by = %s, revoked_at = now(),
                            revoked_reason = %s, updated_at = now()
                        WHERE rule_code = %s
                        """,
                        (actor.strip(), reason.strip(), rule_code),
                    )
                    result = self._content_rule(cur, rule_code)
                else:
                    raise FunctionalKnowledgeConflictError("Only approved content rules can be revoked")
            self.c.commit()
        except Exception:
            self.c.rollback()
            raise
        return result

    def approve_source_evidence(self, evidence_code: str, approved_by: str) -> dict[str, Any] | None:
        try:
            with self.c.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM functional_knowledge_source_evidences WHERE evidence_code = %s FOR UPDATE",
                    (evidence_code,),
                )
                source = cur.fetchone()
                if source is None:
                    self.c.rollback()
                    return None
                if source["status"] == "approved":
                    self.c.commit()
                    return dict(source)
                if source["status"] != "draft":
                    raise FunctionalKnowledgeConflictError("Only draft source evidence can be approved")
                cur.execute(
                    """UPDATE functional_knowledge_source_evidences
                       SET status = 'approved', approved_by = %s, approved_at = now(), updated_at = now()
                       WHERE evidence_code = %s RETURNING *""",
                    (approved_by, evidence_code),
                )
                row = cur.fetchone()
            self.c.commit()
        except Exception:
            self.c.rollback()
            raise
        return dict(row)

    def reject_source_evidence(
        self, evidence_code: str, actor: str, reason: str
    ) -> dict[str, Any] | None:
        try:
            with self.c.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM functional_knowledge_source_evidences WHERE evidence_code = %s FOR UPDATE",
                    (evidence_code,),
                )
                source = cur.fetchone()
                if source is None:
                    self.c.rollback()
                    return None
                if source["status"] == "rejected":
                    result = dict(source)
                elif source["status"] == "draft":
                    cur.execute(
                        """UPDATE functional_knowledge_source_evidences
                           SET status = 'rejected', rejected_by = %s, rejected_at = now(),
                               rejection_reason = %s, updated_at = now()
                           WHERE evidence_code = %s RETURNING *""",
                        (actor.strip(), reason.strip(), evidence_code),
                    )
                    result = dict(cur.fetchone())
                else:
                    raise FunctionalKnowledgeConflictError(
                        "Only draft source evidence can be rejected"
                    )
            self.c.commit()
        except Exception:
            self.c.rollback()
            raise
        return result

    def revoke_source_evidence(
        self, evidence_code: str, actor: str, reason: str
    ) -> dict[str, Any] | None:
        try:
            with self.c.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM functional_knowledge_source_evidences WHERE evidence_code = %s FOR UPDATE",
                    (evidence_code,),
                )
                source = cur.fetchone()
                if source is None:
                    self.c.rollback()
                    return None
                if source["status"] == "revoked":
                    result = dict(source)
                elif source["status"] == "approved":
                    cur.execute(
                        """UPDATE functional_knowledge_source_evidences
                           SET status = 'revoked', revoked_by = %s, revoked_at = now(),
                               revoked_reason = %s, updated_at = now()
                           WHERE evidence_code = %s RETURNING *""",
                        (actor.strip(), reason.strip(), evidence_code),
                    )
                    result = dict(cur.fetchone())
                    cur.execute(
                        """SELECT fact_code FROM functional_knowledge_fact_claims
                           WHERE source_evidence_code = %s FOR UPDATE""",
                        (evidence_code,),
                    )
                    for fact_code in {row["fact_code"] for row in cur.fetchall()}:
                        self._refresh_fact_status(cur, fact_code)
                else:
                    raise FunctionalKnowledgeConflictError(
                        "Only approved source evidence can be revoked"
                    )
            self.c.commit()
        except Exception:
            self.c.rollback()
            raise
        return result

    def create_fact_claim(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            with self.c.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM functional_knowledge_source_evidences WHERE evidence_code = %s FOR UPDATE",
                    (payload["source_evidence_code"],),
                )
                source = cur.fetchone()
                if source is None:
                    self.c.rollback()
                    return None
                if source["status"] != "approved":
                    raise FunctionalKnowledgeConflictError("Fact claims require approved source evidence")
                citation = payload["citation_excerpt"].strip()
                requested_start = payload.get("citation_start_offset")
                requested_end = payload.get("citation_end_offset")
                if requested_start is None:
                    citation_start = source["excerpt"].find(citation)
                    citation_end = citation_start + len(citation)
                else:
                    citation_start = int(requested_start)
                    citation_end = int(requested_end)
                if (
                    citation_start < 0
                    or citation_end > len(source["excerpt"])
                    or source["excerpt"][citation_start:citation_end] != citation
                ):
                    raise FunctionalKnowledgeConflictError("Citation excerpt must be contained in the approved evidence excerpt")
                fact_code = self._next(cur, "functional_knowledge_fact", "FACT")
                cur.execute(
                    """INSERT INTO functional_knowledge_facts
                       (fact_code,title,claim,source_url,related_codes,status,source_evidence_code)
                       VALUES(%s,%s,%s,%s,%s,'draft',%s)""",
                    (
                        fact_code,
                        payload["fact_title"],
                        payload["claim"],
                        source["source_url"],
                        Jsonb(list(dict.fromkeys(payload.get("related_codes") or []))),
                        source["evidence_code"],
                    ),
                )
                claim_code = self._next(cur, "functional_knowledge_fact_claim", "CLAIM")
                fingerprint = canonical_fingerprint(
                    {
                        "fact_code": fact_code,
                        "source_evidence_code": source["evidence_code"],
                        "field_path": payload.get("field_path"),
                        "claim": payload["claim"],
                        "citation_excerpt": citation,
                        "citation_start_offset": citation_start,
                        "citation_end_offset": citation_end,
                        "valid_from": payload.get("valid_from"),
                        "valid_until": payload.get("valid_until"),
                    }
                )
                cur.execute(
                    """INSERT INTO functional_knowledge_fact_claims
                       (claim_code,fact_code,source_evidence_code,field_path,claim,citation_excerpt,citation_start_offset,citation_end_offset,valid_from,valid_until,created_by,fingerprint_sha256)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING claim_code""",
                    (
                        claim_code,
                        fact_code,
                        source["evidence_code"],
                        payload.get("field_path"),
                        payload["claim"],
                        citation,
                        citation_start,
                        citation_end,
                        payload.get("valid_from"),
                        payload.get("valid_until"),
                        payload.get("created_by"),
                        fingerprint,
                    ),
                )
                created = cur.fetchone()
                row = self._claim(cur, created["claim_code"])
            self.c.commit()
        except Exception:
            self.c.rollback()
            raise
        return row

    def list_fact_claims(self, q: str | None = None) -> list[dict[str, Any]]:
        with self.c.cursor(row_factory=dict_row) as cur:
            if q:
                pattern = f"%{q.strip()}%"
                cur.execute(
                    self._claim_query("WHERE claim.claim ILIKE %s OR fact.title ILIKE %s"),
                    (pattern, pattern),
                )
            else:
                cur.execute(self._claim_query())
            return [dict(row) for row in cur.fetchall()]

    def resolve_approved_fact_claim(self, claim_code: str) -> dict[str, Any] | None:
        with self.c.cursor(row_factory=dict_row) as cur:
            cur.execute(
                self._claim_query(
                    "WHERE claim.claim_code = %s AND claim.status = 'approved' "
                    "AND source.status = 'approved' AND fact.status = 'approved'"
                ),
                (claim_code,),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def get_fact_claim_lineage(self, claim_code: str) -> dict[str, Any] | None:
        """Project an explicitly pinned claim through the local content chain.

        This is deliberately a relational read model.  It only follows immutable
        project revisions and their source revision IDs; a text-search hit or a
        current project selection is never treated as a historical use.
        """
        with self.c.cursor(row_factory=dict_row) as cur:
            claim = self._claim(cur, claim_code)
            if claim is None:
                return None

            claim_ref = Jsonb([{"claim_code": claim_code}])
            claim_codes = Jsonb([claim_code])
            cur.execute(
                """
                SELECT id, project_code, revision_number, status, created_at
                FROM content_project_revisions
                WHERE content -> 'fact_claim_refs' @> %s
                   OR content -> 'fact_claim_codes' @> %s
                ORDER BY created_at DESC, project_code, revision_number
                """,
                (claim_ref, claim_codes),
            )
            projects = cur.fetchall()

            uses: list[dict[str, Any]] = []
            story_ids: list[Any] = []
            for project in projects:
                uses.append(
                    self._lineage_use(
                        "pins_fact_claim",
                        "content_project",
                        project["project_code"],
                        project["revision_number"],
                        project["status"],
                        project["created_at"],
                    )
                )
                cur.execute(
                    """
                    SELECT id, story_brief_code, revision_number, status, created_at
                    FROM story_brief_revisions
                    WHERE source_project_revision_id = %s
                    ORDER BY created_at, revision_number
                    """,
                    (project["id"],),
                )
                for story in cur.fetchall():
                    story_ids.append(story["id"])
                    uses.append(
                        self._lineage_use(
                            "derived_from",
                            "story_brief",
                            story["story_brief_code"],
                            story["revision_number"],
                            story["status"],
                            story["created_at"],
                        )
                    )
                    cur.execute(
                        """
                        SELECT id, script_revision_code, revision_number, status, created_at
                        FROM content_script_revisions
                        WHERE source_story_brief_revision_id = %s
                        ORDER BY created_at, revision_number
                        """,
                        (story["id"],),
                    )
                    for script in cur.fetchall():
                        uses.append(
                            self._lineage_use(
                                "derived_from",
                                "content_script",
                                script["script_revision_code"],
                                script["revision_number"],
                                script["status"],
                                script["created_at"],
                            )
                        )
                        cur.execute(
                            """
                            SELECT id, program_revision_code, revision_number, status, created_at
                            FROM content_program_revisions
                            WHERE source_script_revision_id = %s
                            ORDER BY created_at, revision_number
                            """,
                            (script["id"],),
                        )
                        for program in cur.fetchall():
                            uses.append(
                                self._lineage_use(
                                    "derived_from",
                                    "content_program",
                                    program["program_revision_code"],
                                    program["revision_number"],
                                    program["status"],
                                    program["created_at"],
                                )
                            )
                            cur.execute(
                                """
                                SELECT shot_list_revision_code, revision_number, status, created_at
                                FROM shot_list_revisions
                                WHERE source_program_revision_id = %s
                                ORDER BY created_at, revision_number
                                """,
                                (program["id"],),
                            )
                            for shot_list in cur.fetchall():
                                uses.append(
                                    self._lineage_use(
                                        "derived_from",
                                        "shot_list",
                                        shot_list["shot_list_revision_code"],
                                        shot_list["revision_number"],
                                        shot_list["status"],
                                        shot_list["created_at"],
                                    )
                                )

            variant_codes: list[str] = []
            if story_ids:
                cur.execute(
                    """
                    SELECT variant_code, revision_number, carrier_kind, status, created_at
                    FROM production_variant_revisions
                    WHERE source_story_brief_revision_id = ANY(%s)
                    ORDER BY created_at, variant_code, revision_number
                    """,
                    (story_ids,),
                )
                for variant in cur.fetchall():
                    variant_codes.append(variant["variant_code"])
                    uses.append(
                        self._lineage_use(
                            "derived_from",
                            f"{variant['carrier_kind']}_variant",
                            variant["variant_code"],
                            variant["revision_number"],
                            variant["status"],
                            variant["created_at"],
                        )
                    )

            plan_codes: list[str] = []
            release_codes: list[str] = []
            if variant_codes:
                cur.execute(
                    """
                    SELECT plan_code, release_code, created_at
                    FROM functional_video_plans
                    WHERE variant_code = ANY(%s)
                    ORDER BY created_at, plan_code
                    """,
                    (variant_codes,),
                )
                for plan in cur.fetchall():
                    plan_codes.append(plan["plan_code"])
                    if plan["release_code"]:
                        release_codes.append(plan["release_code"])
                    uses.append(
                        self._lineage_use(
                            "planned_as", "rendered_video_plan", plan["plan_code"], None, "active", plan["created_at"]
                        )
                    )
                cur.execute(
                    """
                    SELECT plan_code, release_code, status, created_at
                    FROM functional_live_room_plans
                    WHERE variant_code = ANY(%s)
                    ORDER BY created_at, plan_code
                    """,
                    (variant_codes,),
                )
                for plan in cur.fetchall():
                    plan_codes.append(plan["plan_code"])
                    if plan["release_code"]:
                        release_codes.append(plan["release_code"])
                    uses.append(
                        self._lineage_use(
                            "planned_as", "live_room_plan", plan["plan_code"], None, plan["status"], plan["created_at"]
                        )
                    )

            if release_codes:
                cur.execute(
                    """
                    SELECT release_code, current_manifest_revision, status, created_at
                    FROM releases
                    WHERE release_code = ANY(%s)
                    ORDER BY created_at, release_code
                    """,
                    (list(dict.fromkeys(release_codes)),),
                )
                for release in cur.fetchall():
                    uses.append(
                        self._lineage_use(
                            "released_as",
                            "release",
                            release["release_code"],
                            release["current_manifest_revision"],
                            release["status"],
                            release["created_at"],
                        )
                    )

            if plan_codes:
                cur.execute(
                    """
                    SELECT exposure.exposure_code, exposure.session_code, exposure.status, exposure.created_at
                    FROM functional_content_exposures AS exposure
                    WHERE exposure.plan_code = ANY(%s)
                    ORDER BY exposure.created_at, exposure.exposure_code
                    """,
                    (list(dict.fromkeys(plan_codes)),),
                )
                observed_sessions: set[str] = set()
                for exposure in cur.fetchall():
                    if exposure["session_code"] in observed_sessions:
                        continue
                    observed_sessions.add(exposure["session_code"])
                    uses.append(
                        self._lineage_use(
                            "exposed_during",
                            "operation_session",
                            exposure["session_code"],
                            None,
                            exposure["status"],
                            exposure["created_at"],
                        )
                    )

            cur.execute(
                """
                SELECT effect_code, revision_number, status, created_at
                FROM functional_effect_estimates
                WHERE effect_payload @> %s
                   OR effect_payload @> %s
                ORDER BY created_at, effect_code, revision_number
                """,
                (
                    Jsonb({"subject_snapshot": {"content": {"fact_claim_refs": [{"claim_code": claim_code}]}}}),
                    Jsonb({"subject_snapshot": {"content": {"fact_claim_codes": [claim_code]}}}),
                ),
            )
            for effect in cur.fetchall():
                uses.append(
                    self._lineage_use(
                        "estimated_effect_on",
                        "effect_estimate",
                        effect["effect_code"],
                        effect["revision_number"],
                        effect["status"],
                        effect["created_at"],
                    )
                )

        return {
            "claim_code": claim["claim_code"],
            "fact_code": claim["fact_code"],
            "fact_title": claim["fact_title"],
            "claim_status": claim["status"],
            "fact_status": claim["fact_status"],
            "source_evidence_code": claim["source_evidence_code"],
            "source_title": claim["source_title"],
            "source_status": claim["source_status"],
            "uses": sorted(
                uses,
                key=lambda row: (row["created_at"], row["object_type"], row["object_code"]),
                reverse=True,
            ),
        }

    def approve_fact_claim(self, claim_code: str, approved_by: str) -> dict[str, Any] | None:
        try:
            with self.c.cursor(row_factory=dict_row) as cur:
                row = self._claim(cur, claim_code, lock=True)
                if row is None:
                    self.c.rollback()
                    return None
                if row["status"] == "approved":
                    self.c.commit()
                    return row
                if row["status"] != "draft":
                    raise FunctionalKnowledgeConflictError("Only draft fact claims can be approved")
                if row["source_status"] != "approved":
                    raise FunctionalKnowledgeConflictError("Fact claim source evidence is no longer approved")
                cur.execute(
                    """UPDATE functional_knowledge_fact_claims
                       SET status = 'approved', approved_by = %s, approved_at = now(), updated_at = now()
                       WHERE claim_code = %s""",
                    (approved_by, claim_code),
                )
                cur.execute(
                    "UPDATE functional_knowledge_facts SET status = 'approved' WHERE fact_code = %s",
                    (row["fact_code"],),
                )
                result = self._claim(cur, claim_code)
            self.c.commit()
        except Exception:
            self.c.rollback()
            raise
        return result

    def reject_fact_claim(
        self, claim_code: str, actor: str, reason: str
    ) -> dict[str, Any] | None:
        try:
            with self.c.cursor(row_factory=dict_row) as cur:
                row = self._claim(cur, claim_code, lock=True)
                if row is None:
                    self.c.rollback()
                    return None
                if row["status"] == "rejected":
                    result = row
                elif row["status"] == "draft":
                    cur.execute(
                        """UPDATE functional_knowledge_fact_claims
                           SET status = 'rejected', rejected_by = %s, rejected_at = now(),
                               rejection_reason = %s, updated_at = now()
                           WHERE claim_code = %s""",
                        (actor.strip(), reason.strip(), claim_code),
                    )
                    cur.execute(
                        "UPDATE functional_knowledge_facts SET status = 'rejected' WHERE fact_code = %s",
                        (row["fact_code"],),
                    )
                    result = self._claim(cur, claim_code)
                else:
                    raise FunctionalKnowledgeConflictError(
                        "Only draft fact claims can be rejected"
                    )
            self.c.commit()
        except Exception:
            self.c.rollback()
            raise
        return result

    def revoke_fact_claim(
        self, claim_code: str, actor: str, reason: str
    ) -> dict[str, Any] | None:
        try:
            with self.c.cursor(row_factory=dict_row) as cur:
                row = self._claim(cur, claim_code, lock=True)
                if row is None:
                    self.c.rollback()
                    return None
                if row["status"] == "revoked":
                    result = row
                elif row["status"] == "approved":
                    cur.execute(
                        """UPDATE functional_knowledge_fact_claims
                           SET status = 'revoked', revoked_by = %s, revoked_at = now(),
                               revoked_reason = %s, updated_at = now()
                           WHERE claim_code = %s""",
                        (actor.strip(), reason.strip(), claim_code),
                    )
                    self._refresh_fact_status(cur, row["fact_code"])
                    result = self._claim(cur, claim_code)
                else:
                    raise FunctionalKnowledgeConflictError(
                        "Only approved fact claims can be revoked"
                    )
            self.c.commit()
        except Exception:
            self.c.rollback()
            raise
        return result

    @staticmethod
    def _claim_query(where: str = "") -> str:
        return f"""SELECT claim.*, fact.title AS fact_title, source.title AS source_title,
                          fact.status AS fact_status, source.status AS source_status,
                          source.content_sha256 AS content_sha256
                   FROM functional_knowledge_fact_claims AS claim
                   JOIN functional_knowledge_facts AS fact ON fact.fact_code = claim.fact_code
                   JOIN functional_knowledge_source_evidences AS source ON source.evidence_code = claim.source_evidence_code
                   {where}
                   ORDER BY claim.created_at DESC, claim.claim_code DESC"""

    @staticmethod
    def _content_rule_query(where: str = "") -> str:
        return f"""SELECT rule.*, source.title AS source_title,
                          source.status AS source_status,
                          source.content_sha256 AS source_content_sha256
                   FROM functional_knowledge_content_rules AS rule
                   LEFT JOIN functional_knowledge_source_evidences AS source
                     ON source.evidence_code = rule.source_evidence_code
                   {where}
                   ORDER BY rule.created_at DESC, rule.rule_code DESC"""

    def _claim(self, cur: Any, claim_code: str, *, lock: bool = False) -> dict[str, Any] | None:
        lock_clause = " FOR UPDATE OF claim, source, fact" if lock else ""
        cur.execute(
            self._claim_query("WHERE claim.claim_code = %s") + lock_clause,
            (claim_code,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def _content_rule(
        self, cur: Any, rule_code: str, *, lock: bool = False
    ) -> dict[str, Any] | None:
        lock_clause = " FOR UPDATE OF rule" if lock else ""
        cur.execute(
            self._content_rule_query("WHERE rule.rule_code = %s") + lock_clause,
            (rule_code,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _require_approved_rule_source(cur: Any, source_evidence_code: Any) -> None:
        if not source_evidence_code:
            return
        cur.execute(
            """
            SELECT status FROM functional_knowledge_source_evidences
            WHERE evidence_code = %s FOR UPDATE
            """,
            (source_evidence_code,),
        )
        source = cur.fetchone()
        if source is None or source["status"] != "approved":
            raise FunctionalKnowledgeConflictError(
                "Content rules require an approved source evidence when a source is declared"
            )

    @staticmethod
    def _lineage_use(
        relation_type: str,
        object_type: str,
        object_code: str,
        revision_number: int | None,
        status: str,
        created_at: datetime,
    ) -> dict[str, Any]:
        return {
            "relation_type": relation_type,
            "object_type": object_type,
            "object_code": object_code,
            "revision_number": revision_number,
            "status": status,
            "created_at": created_at,
        }

    @staticmethod
    def _refresh_fact_status(cur: Any, fact_code: str) -> None:
        """Keep a local fact usable when another approved, active claim still supports it."""
        cur.execute(
            """UPDATE functional_knowledge_facts AS fact
               SET status = CASE WHEN EXISTS (
                    SELECT 1
                    FROM functional_knowledge_fact_claims AS claim
                    JOIN functional_knowledge_source_evidences AS source
                      ON source.evidence_code = claim.source_evidence_code
                    WHERE claim.fact_code = fact.fact_code
                      AND claim.status = 'approved'
                      AND source.status = 'approved'
               ) THEN 'approved' ELSE 'revoked' END
               WHERE fact.fact_code = %s""",
            (fact_code,),
        )

    @staticmethod
    def _next(cur: Any, object_type: str, prefix: str) -> str:
        d = datetime.now(UTC).date()
        cur.execute(
            "INSERT INTO domain_sequences(sequence_date,object_type,current_value) VALUES(%s,%s,1) ON CONFLICT(sequence_date,object_type) DO UPDATE SET current_value=domain_sequences.current_value+1 RETURNING current_value",
            (d, object_type),
        )
        return f"{prefix}-{d:%Y%m%d}-{int(cur.fetchone()['current_value']):06d}"
