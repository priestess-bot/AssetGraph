from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from browser_use_worker.script_layout_checkpoint import (
    AssetGraphScriptLayoutCheckpointStore,
    script_layout_operation_fingerprint,
    script_layout_plan_fingerprint,
)
from browser_use_worker.script_layout_draft_executor import (
    ScriptLayoutDraftActionResult,
    ScriptLayoutDraftResult,
)


@dataclass
class RecordingCheckpointClient:
    calls: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)

    def start_script_layout_execution(self, build_plan_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("start", (build_plan_code, payload)))
        return {
            "execution_code": "MT-EXEC-20260712-000001",
            "plan_fingerprint": "a" * 64,
            "checkpoint_contract": "script_layout_checkpoint_v1",
            "run_attempt_id": payload["run_attempt_id"],
            "lease_token": "55555555-5555-4555-8555-555555555555",
            "lease_version": 1,
            "finalized_at": None,
            "operation_results": [
                {
                    "operation_index": item["operation_index"],
                    "operation_type": item["intent"]["operation_type"],
                    "operation_fingerprint": "b" * 64,
                    "effect_class": (
                        "read_only"
                        if item["intent"]["operation_type"] == "preflight_content_build_plan"
                        else "mutating"
                    ),
                    "intent_snapshot": item["intent"],
                    "checkpoint_state": "not_started",
                }
                for item in payload["operations"]
            ],
        }

    def renew_script_layout_execution(
        self,
        build_plan_code: str,
        execution_code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(("renew", (build_plan_code, execution_code, payload)))
        return {
            "run_attempt_id": payload["run_attempt_id"],
            "lease_token": payload["lease_token"],
            "lease_version": payload["lease_version"],
        }

    def begin_script_layout_execution_operation(
        self,
        build_plan_code: str,
        execution_code: str,
        operation_index: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(("begin", (build_plan_code, execution_code, operation_index, payload)))
        return {
            "operation_index": operation_index,
            "operation_type": "create_scene",
            "operation_fingerprint": payload["operation_fingerprint"],
            "effect_class": "mutating",
            "decision": "execute",
            "checkpoint_state": "prepared",
        }

    def dispatch_script_layout_execution_operation(
        self,
        build_plan_code: str,
        execution_code: str,
        operation_index: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(("dispatch", (build_plan_code, execution_code, operation_index, payload)))
        return {
            "operation_index": operation_index,
            "operation_type": "create_scene",
            "operation_fingerprint": payload["operation_fingerprint"],
            "effect_class": "mutating",
            "decision": "execute",
            "checkpoint_state": "dispatched",
        }

    def complete_script_layout_execution_operation(
        self,
        build_plan_code: str,
        execution_code: str,
        operation_index: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(("complete", (build_plan_code, execution_code, operation_index, payload)))
        return {
            "operation_index": operation_index,
            "operation_type": "create_scene",
            "operation_fingerprint": payload["operation_fingerprint"],
            "effect_class": "mutating",
            "decision": "skip",
            "checkpoint_state": "completed",
            "completion_evidence": payload["evidence"],
        }

    def finalize_script_layout_execution(
        self,
        build_plan_code: str,
        execution_code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(("finalize", (build_plan_code, execution_code, payload)))
        return {"execution_code": execution_code, "execution_status": payload["execution_status"]}




def operation_plan() -> dict[str, Any]:
    return {
        "build_plan_code": "MT-BUILD-20260712-000001",
        "checkpoint_source_fingerprint": "c" * 64,
        "source": "script_content_layout_build_plan_rule_v1",
        "status": "ready",
        "target_live_room_id": "47000002",
        "operations": [
            {
                "operation_type": "preflight_content_build_plan",
                "status": "ready",
                "target_live_room_id": "47000002",
            },
            {
                "operation_type": "create_scene",
                "status": "ready",
                "scene_index": 1,
                "scene_name": "促单",
            }
        ],
    }


def test_fingerprints_are_canonical_and_bind_operation_index() -> None:
    plan = operation_plan()
    reordered = {key: plan[key] for key in reversed(list(plan))}

    assert script_layout_plan_fingerprint(plan, target_live_room_id="47000002") == script_layout_plan_fingerprint(
        reordered,
        target_live_room_id="47000002",
    )
    assert script_layout_operation_fingerprint(plan["build_plan_code"], 0, plan["operations"][0]) != (
        script_layout_operation_fingerprint(plan["build_plan_code"], 1, plan["operations"][0])
    )


def test_fingerprints_ignore_resolution_process_status_but_bind_material_target() -> None:
    plan = operation_plan()
    uploaded = {
        **plan["operations"][0],
        "material_id": 41000,
        "source_material_url": "https://static.example/material.png",
        "material_resolution_status": "uploaded_to_maitu",
    }
    reused = {**uploaded, "material_resolution_status": "reused_assetgraph_binding"}
    changed_target = {**reused, "material_id": 41001}

    assert script_layout_operation_fingerprint(plan["build_plan_code"], 0, uploaded) == (
        script_layout_operation_fingerprint(plan["build_plan_code"], 0, reused)
    )
    assert script_layout_operation_fingerprint(plan["build_plan_code"], 0, reused) != (
        script_layout_operation_fingerprint(plan["build_plan_code"], 0, changed_target)
    )


def test_checkpoint_store_reuses_attempt_and_completion_ids_for_idempotent_retries() -> None:
    client = RecordingCheckpointClient()
    plan = operation_plan()
    store = AssetGraphScriptLayoutCheckpointStore.start(
        client=client,
        operation_plan=plan,
        target_live_room_id="47000002",
    )
    operation = plan["operations"][1]

    store.begin_operation(1, operation)
    store.begin_operation(1, operation)
    store.dispatch_operation(1, operation)
    store.dispatch_operation(1, operation)
    action = ScriptLayoutDraftActionResult(
        operation_index=1,
        operation_type="create_scene",
        operation_name="新建场景：促单",
        action_type="create_draft_scene",
        status="completed",
        summary="scene created and read back",
        scene_index=1,
        scene_name="促单",
        clip_id=416426,
        details={
            "create_result": {
                "verified": True,
                "verification_source": "working_room_readback",
            },
            "go_live_clicked": False,
        },
    )
    store.complete_operation(1, operation, action)
    store.complete_operation(1, operation, action)

    begin_payloads = [call[1][3] for call in client.calls if call[0] == "begin"]
    complete_payloads = [call[1][3] for call in client.calls if call[0] == "complete"]
    assert begin_payloads[0]["attempt_id"] == begin_payloads[1]["attempt_id"]
    assert complete_payloads[0]["completion_id"] == complete_payloads[1]["completion_id"]
    assert complete_payloads[0]["attempt_id"] == begin_payloads[0]["attempt_id"]
    assert complete_payloads[0]["evidence"]["verified"] is True
    assert complete_payloads[0]["evidence"]["clip_id"] == 416426
    assert complete_payloads[0]["evidence"]["go_live_clicked"] is False
    assert "action_details" not in complete_payloads[0]["evidence"]
    assert complete_payloads[0]["operation_result"]["details"] == {
        "summary": "scene created and read back",
        "go_live_clicked": False,
    }


def test_checkpoint_store_does_not_persist_raw_provider_mutation_response() -> None:
    client = RecordingCheckpointClient()
    plan = operation_plan()
    store = AssetGraphScriptLayoutCheckpointStore.start(
        client=client,
        operation_plan=plan,
        target_live_room_id="47000002",
    )
    operation = plan["operations"][1]
    store.begin_operation(1, operation)
    public_url = (
        "https://mytwins-static.oss-cn-hangzhou.aliyuncs.com/images/"
        "b565b64460bb99e0332e494a68cc3c8ed084ade9.jpeg?x-oss-process=style/max_width_1080"
    )
    action = ScriptLayoutDraftActionResult(
        operation_index=1,
        operation_type="create_scene",
        operation_name="新建场景：促单",
        action_type="create_draft_scene",
        status="completed",
        summary="scene created and read back",
        scene_index=1,
        scene_name="促单",
        clip_id=416426,
        details={
            "create_result": {
                "verified": True,
                "verification_source": "working_room_readback",
                "source_material_url": public_url,
                "response": {"url": public_url, "provider_metadata": "not durable"},
            }
        },
    )

    store.complete_operation(1, operation, action)

    payload = next(call[1][3] for call in client.calls if call[0] == "complete")
    assert payload["evidence"]["source_material_url"] == public_url
    assert "response" not in str(payload)
    assert "provider_metadata" not in str(payload)


def test_checkpoint_store_uses_speaker_and_image_identity_for_digital_human() -> None:
    client = RecordingCheckpointClient()
    plan = operation_plan()
    store = AssetGraphScriptLayoutCheckpointStore.start(
        client=client,
        operation_plan=plan,
        target_live_room_id="47000002",
    )
    operation = plan["operations"][1]
    store.begin_operation(1, operation)
    action = ScriptLayoutDraftActionResult(
        operation_index=1,
        operation_type="insert_asset_layer",
        operation_name="插入数字人",
        action_type="reuse_seeded_digital_human",
        status="completed",
        summary="digital human seed reused and read back",
        scene_index=0,
        scene_name="开场",
        clip_id=416425,
        layer_id="scene-00-digital_human",
        layer_type="digital_human",
        details={
            "insert_result": {
                "verified": True,
                "verification_source": "working_room_readback",
                "material_id": 10121044,
                "source_material_id": 40222,
                "source_material_type": "digital_human",
                "source_material_url": "https://mtc.maituai.com/image/20260618_165812_cover.png",
                "speaker_id": 4224,
                "digital_human_image_id": 8856,
                "sound_enabled": False,
            }
        },
    )

    store.complete_operation(1, operation, action)

    payload = next(call[1][3] for call in client.calls if call[0] == "complete")
    assert payload["evidence"]["source_material_id"] is None
    assert payload["evidence"]["source_material_url"] is None
    assert payload["evidence"]["speaker_id"] == 4224
    assert payload["evidence"]["digital_human_image_id"] == 8856
    assert payload["evidence"]["sound_enabled"] is False


def test_checkpoint_store_refuses_unverified_mutation_completion() -> None:
    client = RecordingCheckpointClient()
    plan = operation_plan()
    store = AssetGraphScriptLayoutCheckpointStore.start(
        client=client,
        operation_plan=plan,
        target_live_room_id="47000002",
    )
    operation = plan["operations"][1]
    store.begin_operation(1, operation)
    action = ScriptLayoutDraftActionResult(
        operation_index=1,
        operation_type="create_scene",
        operation_name="新建场景：促单",
        action_type="create_draft_scene",
        status="completed",
        summary="API returned but no authoritative readback",
        scene_index=1,
        scene_name="促单",
        clip_id=416426,
        details={"create_result": {"verified": False}},
    )

    import pytest

    with pytest.raises(RuntimeError, match="authoritative verification"):
        store.complete_operation(1, operation, action)

    assert not any(call[0] == "complete" for call in client.calls)


def test_checkpoint_finalize_updates_same_execution_without_operation_result_reinsert() -> None:
    client = RecordingCheckpointClient()
    store = AssetGraphScriptLayoutCheckpointStore.start(
        client=client,
        operation_plan=operation_plan(),
        target_live_room_id="47000002",
    )
    result = ScriptLayoutDraftResult(
        status="completed_with_manual_review",
        target_live_room_id="47000002",
        ready_for_go_live=False,
        manual_review_required=True,
        summary="draft complete",
        operation_count=1,
        executed_action_count=1,
        skipped_action_count=0,
        placeholder_count=0,
        failure_count=0,
        actions=[],
    )

    finalized = store.finalize(result)

    assert finalized["execution_code"] == "MT-EXEC-20260712-000001"
    finalize_payload = next(call[1][2] for call in client.calls if call[0] == "finalize")
    assert finalize_payload["execution_status"] == "completed_with_manual_review"
    assert "operation_results" not in finalize_payload
