from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row


class WorkflowCompatibilityRepository:
    """Read-only access to legacy WorkflowRun/StepRun projections."""

    def __init__(self, connection: Connection):
        self.connection = connection

    def list_runs(
        self,
        *,
        source_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if source_type:
            clauses.append("source_type = %s")
            values.append(source_type)
        if status:
            clauses.append("status = %s")
            values.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.extend((limit, offset))
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT * FROM legacy_workflow_run_projections_v1
                {where}
                ORDER BY updated_at DESC, projection_run_code
                LIMIT %s OFFSET %s
                """,
                tuple(values),
            )
            rows = cursor.fetchall()
        return [self._serialize(row) for row in rows]

    def get_run(self, projection_run_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM legacy_workflow_run_projections_v1 WHERE projection_run_code = %s",
                (projection_run_code,),
            )
            run = cursor.fetchone()
            if run is None:
                return None
            cursor.execute(
                """
                SELECT * FROM legacy_workflow_step_projections_v1
                WHERE projection_run_code = %s
                ORDER BY sort_order, projection_step_code
                """,
                (projection_run_code,),
            )
            steps = cursor.fetchall()
        result = self._serialize(run)
        result["steps"] = [self._serialize(step) for step in steps]
        return result

    def list_asset_observations(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self._list_projection(
            "legacy_asset_observations_v1",
            order_by="updated_at DESC, projection_code",
            limit=limit,
            offset=offset,
        )

    def list_content_projects(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self._list_projection(
            "legacy_content_project_projections_v1",
            order_by="updated_at DESC, projection_project_code",
            limit=limit,
            offset=offset,
        )

    def list_live_room_variants(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self._list_projection(
            "legacy_live_room_variant_projections_v1",
            order_by="updated_at DESC, projection_variant_code",
            limit=limit,
            offset=offset,
        )

    def list_layout_hypotheses(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self._list_projection(
            "legacy_layout_hypothesis_projections_v1",
            order_by="updated_at DESC, projection_code",
            limit=limit,
            offset=offset,
        )

    def list_delivery_unknown(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self._list_projection(
            "legacy_delivery_unknown_projections_v1",
            order_by="observed_at DESC NULLS LAST, projection_code",
            limit=limit,
            offset=offset,
        )

    def _list_projection(
        self,
        view_name: str,
        *,
        order_by: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        allowed_views = {
            "legacy_asset_observations_v1",
            "legacy_content_project_projections_v1",
            "legacy_live_room_variant_projections_v1",
            "legacy_layout_hypothesis_projections_v1",
            "legacy_delivery_unknown_projections_v1",
        }
        if view_name not in allowed_views:
            raise ValueError("unsupported compatibility projection")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"SELECT * FROM {view_name} ORDER BY {order_by} LIMIT %s OFFSET %s",
                (limit, offset),
            )
            rows = cursor.fetchall()
        return [self._serialize(row) for row in rows]

    @staticmethod
    def _serialize(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for key, value in list(result.items()):
            if isinstance(value, UUID):
                result[key] = str(value)
        return result
