from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.domain.errors import DomainConflictError


@dataclass(frozen=True, slots=True)
class StateMachine:
    name: str
    transitions: Mapping[str, frozenset[str]]
    terminal_states: frozenset[str] = frozenset()

    def require_transition(self, current: str, target: str) -> None:
        allowed = self.transitions.get(current, frozenset())
        if target not in allowed:
            raise DomainConflictError(
                "STATE_TRANSITION_NOT_ALLOWED",
                f"{self.name} cannot transition from {current!r} to {target!r}",
                details={
                    "machine": self.name,
                    "current": current,
                    "target": target,
                    "allowed": sorted(allowed),
                },
            )

    def is_terminal(self, state: str) -> bool:
        return state in self.terminal_states


REVISION_STATE_MACHINE = StateMachine(
    name="immutable_revision",
    transitions={
        "draft": frozenset({"confirmed"}),
        "confirmed": frozenset({"superseded"}),
        "superseded": frozenset(),
    },
    terminal_states=frozenset({"superseded"}),
)

WORKFLOW_STATE_MACHINE = StateMachine(
    name="workflow_run",
    transitions={
        "queued": frozenset({"running", "cancelling", "cancelled", "failed"}),
        "running": frozenset({"waiting_human", "cancelling", "succeeded", "failed", "reconcile_required"}),
        "waiting_human": frozenset({"running", "cancelling", "failed"}),
        "cancelling": frozenset({"cancelled", "reconcile_required"}),
        "reconcile_required": frozenset({"running", "succeeded", "failed", "cancelled"}),
        "cancelled": frozenset(),
        "succeeded": frozenset(),
        "failed": frozenset(),
    },
    terminal_states=frozenset({"cancelled", "succeeded", "failed"}),
)

STEP_STATE_MACHINE = StateMachine(
    name="workflow_step",
    transitions={
        "pending": frozenset({"ready", "cancelled"}),
        "ready": frozenset({"running", "cancelled"}),
        "running": frozenset({"waiting_human", "succeeded", "failed", "cancelled", "reconcile_required"}),
        "waiting_human": frozenset({"ready", "cancelled", "failed"}),
        "reconcile_required": frozenset({"ready", "succeeded", "failed", "cancelled"}),
        "succeeded": frozenset(),
        "failed": frozenset({"ready"}),
        "cancelled": frozenset(),
    },
    terminal_states=frozenset({"succeeded", "cancelled"}),
)

RELEASE_STATE_MACHINE = StateMachine(
    name="release",
    transitions={
        "candidate": frozenset({"validating", "revoked"}),
        "validating": frozenset({"awaiting_approval", "candidate", "revoked"}),
        "awaiting_approval": frozenset({"approved", "candidate", "revoked"}),
        "approved": frozenset({"delivery_pending", "revoked"}),
        "delivery_pending": frozenset({"delivered", "delivery_failed", "reconcile_required", "revoked"}),
        "delivery_failed": frozenset({"delivery_pending", "reconcile_required", "revoked"}),
        "reconcile_required": frozenset({"delivered", "delivery_failed", "revoked"}),
        "delivered": frozenset({"revoked"}),
        "revoked": frozenset(),
    },
    terminal_states=frozenset({"revoked"}),
)

DELIVERY_STATE_MACHINE = StateMachine(
    name="delivery_attempt",
    transitions={
        "prepared": frozenset({"authorized", "cancelled"}),
        "authorized": frozenset({"committing", "cancelled"}),
        "committing": frozenset({"succeeded", "failed", "reconcile_required"}),
        "reconcile_required": frozenset({"succeeded", "failed"}),
        "succeeded": frozenset(),
        "failed": frozenset(),
        "cancelled": frozenset(),
    },
    terminal_states=frozenset({"succeeded", "failed", "cancelled"}),
)

DELETION_RUN_STATE_MACHINE = StateMachine(
    name="deletion_run",
    transitions={
        "requested": frozenset({"validating", "rejected"}),
        "validating": frozenset({"blocked_by_legal_hold", "approved", "rejected"}),
        "blocked_by_legal_hold": frozenset({"validating", "rejected"}),
        "approved": frozenset({"executing", "rejected"}),
        "executing": frozenset({"verifying"}),
        "verifying": frozenset({"completed", "partial_failed"}),
        "partial_failed": frozenset({"executing", "rejected"}),
        "completed": frozenset(),
        "rejected": frozenset(),
    },
    terminal_states=frozenset({"completed", "rejected"}),
)
