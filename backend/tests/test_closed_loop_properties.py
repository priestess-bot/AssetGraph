from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from hypothesis import given, settings, strategies as st

from app.domain.contracts import canonical_fingerprint, canonical_json_bytes
from app.domain.errors import DomainConflictError
from app.domain.state_machines import (
    DELIVERY_STATE_MACHINE,
    RELEASE_STATE_MACHINE,
    REVISION_STATE_MACHINE,
    STEP_STATE_MACHINE,
    WORKFLOW_STATE_MACHINE,
)
from app.repositories.content_core import ContentCoreRepository


MACHINES = (
    REVISION_STATE_MACHINE,
    WORKFLOW_STATE_MACHINE,
    STEP_STATE_MACHINE,
    RELEASE_STATE_MACHINE,
    DELIVERY_STATE_MACHINE,
)
STATE_NAMES = sorted(
    {state for machine in MACHINES for state in machine.transitions}
    | {target for machine in MACHINES for values in machine.transitions.values() for target in values}
    | {"unknown_state"}
)


@given(
    machine=st.sampled_from(MACHINES),
    current=st.sampled_from(STATE_NAMES),
    target=st.sampled_from(STATE_NAMES),
)
def test_every_state_machine_edge_is_either_declared_or_stably_rejected(machine, current: str, target: str) -> None:
    if target in machine.transitions.get(current, frozenset()):
        machine.require_transition(current, target)
    else:
        with pytest.raises(DomainConflictError) as rejected:
            machine.require_transition(current, target)
        assert rejected.value.code == "STATE_TRANSITION_NOT_ALLOWED"
        assert rejected.value.details == {
            "machine": machine.name,
            "current": current,
            "target": target,
            "allowed": sorted(machine.transitions.get(current, frozenset())),
        }


@given(
    pairs=st.lists(
        st.tuples(
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=12),
            st.integers(min_value=-1_000_000, max_value=1_000_000),
        ),
        min_size=1,
        max_size=20,
        unique_by=lambda pair: pair[0],
    )
)
def test_canonical_fingerprint_is_invariant_under_arbitrary_mapping_insertion_order(
    pairs: list[tuple[str, int]],
) -> None:
    forward = dict(pairs)
    reverse = dict(reversed(pairs))
    assert canonical_json_bytes(forward) == canonical_json_bytes(reverse)
    assert canonical_fingerprint(forward) == canonical_fingerprint(reverse)


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")
@settings(max_examples=5, deadline=None)
@given(
    goals=st.lists(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=1, max_size=30).filter(str.strip),
        min_size=1,
        max_size=4,
        unique=True,
    )
)
def test_arbitrary_project_revision_sequences_are_monotonic_immutable_and_idempotent(
    goals: list[str],
) -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository = ContentCoreRepository(connection)
        created = repository.create_project(
            title=f"Property {suffix}",
            generation_goal=goals[0],
            content={"sequence": 1},
            actor_id="property-test",
        )
        project_code = created["project_code"]
        confirmed = repository.confirm_project_revision(
            project_code,
            revision_number=1,
            actor_id="property-test",
        )
        replay = repository.confirm_project_revision(
            project_code,
            revision_number=1,
            actor_id="property-test",
        )
        assert replay["id"] == confirmed["id"]

        for revision_number, goal in enumerate(goals[1:], start=2):
            prior_revision = revision_number - 1
            repository.add_derivation_edge(
                source_type="content_project",
                source_code=project_code,
                source_revision=prior_revision,
                target_type="build_plan",
                target_code=f"PLAN-{suffix}-{prior_revision}",
                target_revision=prior_revision,
                relation_type="derived_from",
                producer_role="property_test",
                producer_strategy_revision="property-test.v1",
                input_fingerprint=f"{prior_revision:064x}",
                output_fingerprint=f"{revision_number:064x}",
            )
            revision = repository.create_project_revision(
                project_code,
                expected_revision=prior_revision,
                title=created["title"],
                generation_goal=goal,
                content={"sequence": revision_number},
                source_revision_refs=[
                    {
                        "object_type": "content_project",
                        "code": project_code,
                        "revision": prior_revision,
                    }
                ],
                actor_id="property-test",
            )
            assert revision["revision_number"] == revision_number
            confirmed = repository.confirm_project_revision(
                project_code,
                revision_number=revision_number,
                actor_id="property-test",
            )
            replay = repository.confirm_project_revision(
                project_code,
                revision_number=revision_number,
                actor_id="property-test",
            )
            assert replay["id"] == confirmed["id"]
            prior = repository.get_project_revision(project_code, prior_revision)
            assert prior is not None and prior["status"] == "superseded"
            stale = repository.list_active_stale_records(
                target_type="build_plan",
                target_code=f"PLAN-{suffix}-{prior_revision}",
            )
            assert stale and stale[0]["new_revision"] == revision_number

        latest = repository.get_project(project_code)
        assert latest is not None
        assert latest["revision_number"] == len(goals)
        assert latest["status"] == "confirmed"
