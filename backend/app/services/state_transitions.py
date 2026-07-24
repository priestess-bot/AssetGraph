from __future__ import annotations

from uuid import uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.domain.errors import DomainConflictError
from app.domain.state_machines import StateMachine


def require_audited_transition(
    connection: Connection,
    machine: StateMachine,
    *,
    current: str,
    target: str,
    principal_type: str,
    principal_id: str | None,
    target_type: str,
    target_code: str,
    target_revision: int | None = None,
    trace_id: str | None = None,
) -> None:
    try:
        machine.require_transition(current, target)
    except DomainConflictError as exc:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO audit_events (
                    audit_event_id, principal_type, principal_id, action,
                    target_type, target_code, target_revision, outcome,
                    reason_code, trace_id, details
                )
                VALUES (%s, %s, %s, 'state_transition', %s, %s, %s,
                        'denied', %s, %s, %s)
                """,
                (
                    uuid4(),
                    principal_type,
                    principal_id,
                    target_type,
                    target_code,
                    target_revision,
                    exc.code,
                    trace_id,
                    Jsonb(
                        {
                            "machine": machine.name,
                            "current": current,
                            "requested_target": target,
                            "allowed": sorted(machine.transitions.get(current, frozenset())),
                        }
                    ),
                ),
            )
        connection.commit()
        raise
