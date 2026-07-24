from __future__ import annotations
import hashlib
from datetime import UTC, datetime
from typing import Any
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from app.domain.errors import DomainValidationError


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

    def create_experiment(self, p: dict[str, Any]) -> dict[str, Any]:
        variants = list(dict.fromkeys(p["variants"]))
        if len(variants) != 2:
            raise DomainValidationError(
                "EXPERIMENT_VARIANTS_INVALID",
                "Exactly two unique variants are required",
            )
        with self.connection.cursor(row_factory=dict_row) as c:
            code = self._next(c, "EXP", "functional_experiment")
            c.execute(
                "INSERT INTO functional_experiments (experiment_code,title,metric_key,variants) VALUES (%s,%s,%s,%s) RETURNING *",
                (code, p["title"], p["metric_key"], Jsonb(variants)),
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
            variants = e["variants"]
            variant = variants[
                int(hashlib.sha256(p["subject_key"].encode()).hexdigest(), 16) % 2
            ]
            c.execute(
                "INSERT INTO functional_experiment_outcomes (experiment_code,subject_key,variant_key,metric_value) VALUES (%s,%s,%s,%s) ON CONFLICT (experiment_code,subject_key) DO UPDATE SET metric_value=EXCLUDED.metric_value RETURNING id",
                (code, p["subject_key"], variant, p["metric_value"]),
            )
        self.connection.commit()
        return self.get_experiment(code)

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
    def _next(c: Any, prefix: str, kind: str) -> str:
        date = datetime.now(UTC).date()
        c.execute(
            "INSERT INTO domain_sequences(sequence_date,object_type,current_value) VALUES(%s,%s,1) ON CONFLICT(sequence_date,object_type) DO UPDATE SET current_value=domain_sequences.current_value+1 RETURNING current_value",
            (date, kind),
        )
        return f"{prefix}-{date:%Y%m%d}-{int(c.fetchone()['current_value']):06d}"
