from __future__ import annotations
from datetime import UTC, datetime
from typing import Any
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class FunctionalKnowledgeService:
    def __init__(self, c: Connection):
        self.c = c

    def create(self, p: dict[str, Any]) -> dict[str, Any]:
        with self.c.cursor(row_factory=dict_row) as cur:
            code = self._next(cur)
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

    @staticmethod
    def _next(cur: Any) -> str:
        d = datetime.now(UTC).date()
        cur.execute(
            "INSERT INTO domain_sequences(sequence_date,object_type,current_value) VALUES(%s,'functional_knowledge_fact',1) ON CONFLICT(sequence_date,object_type) DO UPDATE SET current_value=domain_sequences.current_value+1 RETURNING current_value",
            (d,),
        )
        return f"FACT-{d:%Y%m%d}-{int(cur.fetchone()['current_value']):06d}"
