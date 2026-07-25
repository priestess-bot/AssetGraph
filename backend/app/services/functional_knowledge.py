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
                if citation not in source["excerpt"]:
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
                        "valid_from": payload.get("valid_from"),
                        "valid_until": payload.get("valid_until"),
                    }
                )
                cur.execute(
                    """INSERT INTO functional_knowledge_fact_claims
                       (claim_code,fact_code,source_evidence_code,field_path,claim,citation_excerpt,valid_from,valid_until,created_by,fingerprint_sha256)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING claim_code""",
                    (
                        claim_code,
                        fact_code,
                        source["evidence_code"],
                        payload.get("field_path"),
                        payload["claim"],
                        citation,
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

    @staticmethod
    def _claim_query(where: str = "") -> str:
        return f"""SELECT claim.*, fact.title AS fact_title, source.title AS source_title,
                          source.status AS source_status, source.content_sha256 AS content_sha256
                   FROM functional_knowledge_fact_claims AS claim
                   JOIN functional_knowledge_facts AS fact ON fact.fact_code = claim.fact_code
                   JOIN functional_knowledge_source_evidences AS source ON source.evidence_code = claim.source_evidence_code
                   {where}
                   ORDER BY claim.created_at DESC, claim.claim_code DESC"""

    def _claim(self, cur: Any, claim_code: str, *, lock: bool = False) -> dict[str, Any] | None:
        lock_clause = " FOR UPDATE OF claim, source, fact" if lock else ""
        cur.execute(
            self._claim_query("WHERE claim.claim_code = %s") + lock_clause,
            (claim_code,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _next(cur: Any, object_type: str, prefix: str) -> str:
        d = datetime.now(UTC).date()
        cur.execute(
            "INSERT INTO domain_sequences(sequence_date,object_type,current_value) VALUES(%s,%s,1) ON CONFLICT(sequence_date,object_type) DO UPDATE SET current_value=domain_sequences.current_value+1 RETURNING current_value",
            (d, object_type),
        )
        return f"{prefix}-{d:%Y%m%d}-{int(cur.fetchone()['current_value']):06d}"
