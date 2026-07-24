from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

from app.domain.contracts import DataClassification
from app.domain.errors import DomainAuthorizationError
from app.repositories.privacy_governance import PrivacyGovernanceRepository
from app.services.privacy_governance import DATA_ACCESS_ACTIONS, DataAccessRequest, DataAccessService


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def _request(
    suffix: str,
    *,
    roles: frozenset[str],
    purpose: str,
    action: str,
    data_classification: DataClassification,
) -> DataAccessRequest:
    return DataAccessRequest(
        principal_id=f"principal-{suffix}",
        roles=roles,
        purpose=purpose,
        action=action,
        resource_type="artifact",
        resource_code=f"ART-{suffix}",
        data_classification=data_classification,
        trace_id="a" * 32,
    )


def test_role_purpose_action_and_class_must_match_one_grant_and_are_audited() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        service = DataAccessService(PrivacyGovernanceRepository(connection))
        allowed = service.authorize(
            _request(
                suffix,
                roles=frozenset({"data_operator"}),
                purpose="analytics",
                action="export",
                data_classification=DataClassification.CONFIDENTIAL,
            )
        )
        assert allowed["decision"] == "allow"

        with pytest.raises(DomainAuthorizationError) as denied:
            service.authorize(
                _request(
                    suffix,
                    roles=frozenset({"graph_operator", "production_operator"}),
                    purpose="knowledge_projection",
                    action="model_call",
                    data_classification=DataClassification.INTERNAL,
                )
            )
        assert denied.value.code == "DATA_ACCESS_DENIED"

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT decision, action, purpose FROM data_access_decisions
                WHERE principal_id = %s ORDER BY decided_at
                """,
                (f"principal-{suffix}",),
            )
            assert cursor.fetchall() == [
                ("allow", "export", "analytics"),
                ("deny", "model_call", "knowledge_projection"),
            ]


def test_baseline_covers_all_governed_actions_and_restricted_graph_access_is_denied() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository = PrivacyGovernanceRepository(connection)
        policy = repository.get_active_access_policy("baseline-purpose-bound-access")
        assert policy is not None
        configured_actions = {
            action
            for grants in policy["rules"]["role_grants"].values()
            for grant in grants
            for action in grant["actions"]
        }
        assert configured_actions == DATA_ACCESS_ACTIONS

        with pytest.raises(DomainAuthorizationError):
            DataAccessService(repository).authorize(
                _request(
                    suffix,
                    roles=frozenset({"graph_operator"}),
                    purpose="knowledge_projection",
                    action="graph_query",
                    data_classification=DataClassification.RESTRICTED_PERSONAL,
                )
            )
