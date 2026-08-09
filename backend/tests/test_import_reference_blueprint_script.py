from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest


ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from import_reference_blueprint import (  # noqa: E402
    ROOM_TEMPLATE_ROOT,
    build_revision_payload,
    canonical_json_checksum,
    identity_marker,
    materialize_room_template,
    run_import,
)


def sample_payload() -> dict[str, Any]:
    return {
        "reference_profile": {
            "profile_code": "MT-REF-20260709-39826",
            "reference_room_id": "39826",
        },
        "blueprint": {
            "blueprint_code": "MT-BP-20260709-39826",
            "reference_room_id": "39826",
            "title": "Reference room blueprint",
            "scenes": [
                {
                    "scene_code": "MT-SCENE-001",
                    "scene_name": "Scene 1",
                    "goal": "Product introduction",
                    "estimated_duration_seconds": 30,
                    "reference_active": True,
                    "layers": [
                        {
                            "layer_code": "MT-LAYER-001",
                            "layer_name": "Foreground",
                            "layer_role": "foreground_frame",
                            "required_category": "floating_sticker",
                            "accepted_asset_types": ["IMG"],
                            "replacement_policy": "keep_layout",
                            "sort_order": 1,
                        }
                    ],
                }
            ],
            "script_blocks": [
                {"scene_name": "Scene 1", "content": "Reference script"}
            ],
        },
    }


class FakeApiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.templates: dict[str, dict[str, Any]] = {}
        self.next_template = 1
        self.imported = {
            "id": "blueprint-id",
            "blueprint_code": "MT-BP-20260709-39826",
        }

    def seed_template(
        self,
        *,
        template_code: str,
        blueprint_code: str,
        room_id: str,
        template_kind: str = "layout_hypothesis",
        revisions: list[dict[str, Any]] | None = None,
    ) -> None:
        revisions = copy.deepcopy(revisions or [])
        self.templates[template_code] = {
            "id": f"id-{template_code}",
            "template_code": template_code,
            "name": template_code,
            "description": identity_marker(blueprint_code, room_id),
            "template_kind": template_kind,
            "status": "draft",
            "latest_revision_number": max(
                (item["revision_number"] for item in revisions), default=None
            ),
            "published_revision_number": next(
                (
                    item["revision_number"]
                    for item in revisions
                    if item.get("status") == "published"
                ),
                None,
            ),
            "revisions": revisions,
        }

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append((method, path, copy.deepcopy(payload)))
        if path == "/api/maitu/live-room-blueprints/import-reference":
            assert method == "POST"
            return copy.deepcopy(self.imported)
        if method == "GET" and path.startswith(f"{ROOM_TEMPLATE_ROOT}?"):
            return [self._summary(item) for item in self.templates.values()]
        if method == "POST" and path == ROOM_TEMPLATE_ROOT:
            code = f"LR-TPL-{self.next_template:03d}"
            self.next_template += 1
            self.templates[code] = {
                "id": f"id-{code}",
                "template_code": code,
                "name": payload["name"],
                "description": payload.get("description"),
                "template_kind": payload["template_kind"],
                "status": "draft",
                "latest_revision_number": None,
                "published_revision_number": None,
                "revisions": [],
            }
            return copy.deepcopy(self.templates[code])
        suffix = path.removeprefix(f"{ROOM_TEMPLATE_ROOT}/")
        parts = suffix.split("/")
        template_code = parts[0]
        template = self.templates[template_code]
        if method == "GET" and len(parts) == 1:
            return copy.deepcopy(template)
        if method == "POST" and parts[1:] == ["revisions"]:
            number = len(template["revisions"]) + 1
            revision = {
                **copy.deepcopy(payload),
                "revision_number": number,
                "status": "draft",
            }
            template["revisions"].append(revision)
            template["latest_revision_number"] = number
            template["status"] = "draft"
            return copy.deepcopy(revision)
        if method == "POST" and len(parts) == 4 and parts[1] == "revisions":
            number = int(parts[2])
            assert parts[3] == "publish"
            for revision in template["revisions"]:
                if revision["revision_number"] == number:
                    revision["status"] = "published"
                elif revision.get("status") == "published":
                    revision["status"] = "superseded"
            template["status"] = "published"
            template["published_revision_number"] = number
            return {"template_code": template_code, "revision_number": number}
        raise AssertionError(f"unexpected request: {method} {path}")

    @staticmethod
    def _summary(template: dict[str, Any]) -> dict[str, Any]:
        return {key: copy.deepcopy(value) for key, value in template.items() if key != "revisions"}


def calls_to(client: FakeApiClient, method: str, path_suffix: str) -> list[tuple[str, str, Any]]:
    return [
        call
        for call in client.calls
        if call[0] == method and call[1].endswith(path_suffix)
    ]


def test_run_import_without_materialization_preserves_legacy_api_behavior() -> None:
    client = FakeApiClient()
    payload = sample_payload()

    result = run_import(payload, client=client)

    assert result == client.imported
    assert client.calls == [
        ("POST", "/api/maitu/live-room-blueprints/import-reference", payload)
    ]


def test_materialization_creates_approximate_reference_only_draft() -> None:
    client = FakeApiClient()
    payload = sample_payload()

    result = run_import(payload, client=client, materialize=True)

    room_template = result["room_template"]
    assert room_template["template_action"] == "created"
    assert room_template["revision_action"] == "created"
    assert room_template["publication_action"] == "not_requested"
    create_template = calls_to(client, "POST", ROOM_TEMPLATE_ROOT)[0][2]
    assert create_template["template_kind"] == "layout_hypothesis"
    assert "approximate" in create_template["description"]
    assert "reference_only" in create_template["description"]

    create_revision = calls_to(client, "POST", "/revisions")[0][2]
    checksum = canonical_json_checksum(payload["blueprint"])
    assert create_revision["contract_version"] == "layout-hypothesis.v1"
    assert create_revision["layout_fidelity"] == "approximate"
    assert create_revision["buildability"] == "reference_only"
    assert create_revision["provenance"] == {
        "source_contract": "reference-blueprint-room-template.v1",
        "reference_blueprint_code": "MT-BP-20260709-39826",
        "reference_room_id": "39826",
        "source_checksum_sha256": checksum,
        "checksum_scope": "canonical_blueprint_json",
        "layout_fidelity": "approximate",
        "buildability": "reference_only",
    }
    assert create_revision["layout_reference"]["approximate"] is True
    assert create_revision["layout_reference"]["reference_only"] is True
    assert create_revision["scenes"][0]["scene_key"] == "MT-SCENE-001"
    assert create_revision["components"][0]["component_id"] == "MT-LAYER-001"


def test_repeated_publish_reuses_template_revision_and_publication() -> None:
    client = FakeApiClient()
    payload = sample_payload()

    first = run_import(payload, client=client, materialize=True, publish=True)
    second = run_import(payload, client=client, materialize=True, publish=True)

    assert first["room_template"]["publication_action"] == "published"
    assert second["room_template"] == {
        **first["room_template"],
        "template_action": "reused",
        "revision_action": "reused",
        "publication_action": "reused",
    }
    assert len(calls_to(client, "POST", ROOM_TEMPLATE_ROOT)) == 1
    assert len(calls_to(client, "POST", "/revisions")) == 1
    assert len(calls_to(client, "POST", "/publish")) == 1


def test_publish_existing_draft_does_not_create_another_revision() -> None:
    client = FakeApiClient()
    payload = sample_payload()

    draft = materialize_room_template(payload, client=client, publish=False)
    published = materialize_room_template(payload, client=client, publish=True)

    assert draft["revision_action"] == "created"
    assert published["template_action"] == "reused"
    assert published["revision_action"] == "reused"
    assert published["publication_action"] == "published"
    assert len(calls_to(client, "POST", "/revisions")) == 1


def test_existing_empty_draft_is_recovered_instead_of_duplicated() -> None:
    client = FakeApiClient()
    payload = sample_payload()
    client.seed_template(
        template_code="LR-TPL-RECOVER",
        blueprint_code="MT-BP-20260709-39826",
        room_id="39826",
    )

    result = materialize_room_template(payload, client=client, publish=False)

    assert result["template_code"] == "LR-TPL-RECOVER"
    assert result["template_action"] == "reused"
    assert result["revision_action"] == "created"
    assert len(client.templates) == 1
    assert not calls_to(client, "POST", ROOM_TEMPLATE_ROOT)
    assert len(calls_to(client, "POST", "/revisions")) == 1


def test_changed_blueprint_creates_one_new_revision_on_same_template() -> None:
    client = FakeApiClient()
    payload = sample_payload()
    materialize_room_template(payload, client=client, publish=False)
    changed = copy.deepcopy(payload)
    changed["blueprint"]["title"] = "Updated reference room blueprint"

    second = materialize_room_template(changed, client=client, publish=False)
    third = materialize_room_template(changed, client=client, publish=False)

    assert second["template_action"] == "reused"
    assert second["revision_number"] == 2
    assert second["revision_action"] == "created"
    assert third["revision_number"] == 2
    assert third["revision_action"] == "reused"
    assert len(client.templates) == 1
    assert len(calls_to(client, "POST", "/revisions")) == 2


def test_multiple_matching_templates_fail_closed_before_template_mutation() -> None:
    client = FakeApiClient()
    payload = sample_payload()
    for code in ("LR-TPL-001", "LR-TPL-002"):
        client.seed_template(
            template_code=code,
            blueprint_code="MT-BP-20260709-39826",
            room_id="39826",
        )

    with pytest.raises(RuntimeError, match="multiple room templates match"):
        materialize_room_template(payload, client=client, publish=True)

    assert not calls_to(client, "POST", ROOM_TEMPLATE_ROOT)
    assert not calls_to(client, "POST", "/revisions")
    assert not calls_to(client, "POST", "/publish")


def test_build_revision_requires_at_least_one_scene() -> None:
    payload = sample_payload()
    payload["blueprint"]["scenes"] = []

    with pytest.raises(ValueError, match="at least one scene"):
        build_revision_payload(payload)
