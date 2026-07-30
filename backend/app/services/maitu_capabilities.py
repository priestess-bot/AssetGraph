from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, TypedDict


MaituCapabilityStatus = Literal["verified", "manual_only", "unsupported"]


class _CapabilityDefinition(TypedDict):
    key: str
    title: str
    status: MaituCapabilityStatus
    required_for_draft: bool
    last_verified_at: str | None
    evidence_level: str
    evidence_refs: list[str]
    customer_message: str


_CAPABILITIES: tuple[_CapabilityDefinition, ...] = (
    {
        "key": "read_room",
        "title": "读取直播间",
        "status": "manual_only",
        "required_for_draft": True,
        "last_verified_at": "2026-07-09T18:56:05+08:00",
        "evidence_level": "historical_real_account_readback_without_current_contract_fingerprint",
        "evidence_refs": [
            "docs/maitu-live-room-runs/40147-after-background-script.png",
            "docs/maitu-live-room-runs/38336-zhangyu-summer-readonly-entry.png",
        ],
        "customer_message": "真实账号曾完成房间读取，但缺少当前适配器契约指纹；本轮需重新核对。",
    },
    {
        "key": "verify_blank_non_live",
        "title": "校验空白且未开播",
        "status": "manual_only",
        "required_for_draft": True,
        "last_verified_at": None,
        "evidence_level": "repository_contract_only",
        "evidence_refs": ["workers/browser-use/src/browser_use_worker/browser_cli_session.py"],
        "customer_message": "尚无当前真实账号的完整空房间 canary，执行前需要人工核对。",
    },
    {
        "key": "reuse_default_scene",
        "title": "复用默认场景",
        "status": "manual_only",
        "required_for_draft": False,
        "last_verified_at": None,
        "evidence_level": "repository_contract_only",
        "evidence_refs": ["workers/browser-use/src/browser_use_worker/browser_cli_session.py"],
        "customer_message": "适配器已有操作契约，等待真实账号刷新回读验证。",
    },
    {
        "key": "create_scene",
        "title": "创建场景",
        "status": "manual_only",
        "required_for_draft": True,
        "last_verified_at": None,
        "evidence_level": "repository_contract_only",
        "evidence_refs": ["workers/browser-use/src/browser_use_worker/browser_cli_session.py"],
        "customer_message": "适配器已有操作契约，等待真实账号刷新回读验证。",
    },
    {
        "key": "use_existing_material",
        "title": "使用已有素材",
        "status": "manual_only",
        "required_for_draft": True,
        "last_verified_at": None,
        "evidence_level": "repository_contract_only",
        "evidence_refs": ["workers/browser-use/src/browser_use_worker/browser_cli_session.py"],
        "customer_message": "现有素材身份可进入计划，真实插入仍需 canary。",
    },
    {
        "key": "upload_image",
        "title": "上传普通图片",
        "status": "manual_only",
        "required_for_draft": False,
        "last_verified_at": None,
        "evidence_level": "repository_contract_only",
        "evidence_refs": ["workers/browser-use/src/browser_use_worker/browser_cli_session.py"],
        "customer_message": "当前由客户在麦兔上传；自动上传等待真实账号验证。",
    },
    {
        "key": "upload_video",
        "title": "上传普通视频",
        "status": "manual_only",
        "required_for_draft": False,
        "last_verified_at": None,
        "evidence_level": "repository_contract_only",
        "evidence_refs": ["workers/browser-use/src/browser_use_worker/browser_cli_session.py"],
        "customer_message": "当前由客户在麦兔上传；自动上传等待真实账号验证。",
    },
    {
        "key": "use_existing_digital_human",
        "title": "使用已有数字人和音色",
        "status": "manual_only",
        "required_for_draft": True,
        "last_verified_at": None,
        "evidence_level": "repository_contract_only",
        "evidence_refs": ["workers/browser-use/src/browser_use_worker/browser_cli_session.py"],
        "customer_message": "只复用客户已有资源；绑定与回读等待真实账号验证。",
    },
    {
        "key": "write_script",
        "title": "写入话术",
        "status": "manual_only",
        "required_for_draft": True,
        "last_verified_at": None,
        "evidence_level": "historical_screen_without_current_contract_canary",
        "evidence_refs": ["docs/maitu-live-room-runs/40147-after-background-script.png"],
        "customer_message": "有历史页面结果，但缺少当前契约下完整的变更前后回读。",
    },
    {
        "key": "position_rect_layer",
        "title": "设置矩形图层和层级",
        "status": "manual_only",
        "required_for_draft": True,
        "last_verified_at": None,
        "evidence_level": "repository_contract_only",
        "evidence_refs": ["workers/browser-use/src/browser_use_worker/browser_cli_session.py"],
        "customer_message": "v1 只承诺矩形布局；自动定位等待真实账号验证。",
    },
    {
        "key": "verify_reload_persistence",
        "title": "刷新后回读草稿",
        "status": "manual_only",
        "required_for_draft": True,
        "last_verified_at": None,
        "evidence_level": "repository_contract_only",
        "evidence_refs": [
            "docs/worker-protocols/maitu-browser-use-retry-worker.md",
            "workers/browser-use/src/browser_use_worker/browser_cli_session.py",
        ],
        "customer_message": "尚未完成当前真实账号的写入后刷新回读闭环。",
    },
    {
        "key": "create_live_room",
        "title": "创建直播间",
        "status": "unsupported",
        "required_for_draft": False,
        "last_verified_at": None,
        "evidence_level": "out_of_v1_scope",
        "evidence_refs": ["docs/adr/0003-customer-experience-v1-scope.md"],
        "customer_message": "请先在麦兔创建空白未开播草稿，再填写房间 ID 和标题。",
    },
    {
        "key": "create_digital_human",
        "title": "创建数字人",
        "status": "unsupported",
        "required_for_draft": False,
        "last_verified_at": None,
        "evidence_level": "out_of_v1_scope",
        "evidence_refs": ["docs/adr/0003-customer-experience-v1-scope.md"],
        "customer_message": "v1 只使用麦兔中已经存在的数字人。",
    },
    {
        "key": "create_voice",
        "title": "创建音色",
        "status": "unsupported",
        "required_for_draft": False,
        "last_verified_at": None,
        "evidence_level": "out_of_v1_scope",
        "evidence_refs": ["docs/adr/0003-customer-experience-v1-scope.md"],
        "customer_message": "v1 只使用麦兔中已经存在的音色。",
    },
    {
        "key": "configure_product",
        "title": "配置商品",
        "status": "unsupported",
        "required_for_draft": False,
        "last_verified_at": None,
        "evidence_level": "out_of_v1_scope",
        "evidence_refs": ["docs/adr/0003-customer-experience-v1-scope.md"],
        "customer_message": "商品配置仍由客户在麦兔完成。",
    },
    {
        "key": "configure_interaction",
        "title": "配置互动",
        "status": "unsupported",
        "required_for_draft": False,
        "last_verified_at": None,
        "evidence_level": "out_of_v1_scope",
        "evidence_refs": ["docs/adr/0003-customer-experience-v1-scope.md"],
        "customer_message": "互动配置不在 v1 自动化范围。",
    },
    {
        "key": "schedule",
        "title": "排播",
        "status": "unsupported",
        "required_for_draft": False,
        "last_verified_at": None,
        "evidence_level": "out_of_v1_scope",
        "evidence_refs": ["docs/adr/0003-customer-experience-v1-scope.md"],
        "customer_message": "AssetGraph v1 不排播。",
    },
    {
        "key": "go_live",
        "title": "正式开播",
        "status": "unsupported",
        "required_for_draft": False,
        "last_verified_at": None,
        "evidence_level": "prohibited_by_scope",
        "evidence_refs": ["docs/adr/0003-customer-experience-v1-scope.md"],
        "customer_message": "AssetGraph v1 永远不会点击正式开播。",
    },
)


def maitu_capability_matrix() -> dict[str, Any]:
    """Return the conservative product contract for Maitu integration.

    Repository code proves only that an adapter path exists. Mutations remain
    manual until a current real-account canary provides reload/readback evidence.
    """

    contract = {
        "schema_version": "maitu-capability-matrix.v1",
        "adapter_contract": "maitu-web-working-room.internal.v1",
        "capabilities": list(_CAPABILITIES),
    }
    encoded = json.dumps(contract, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    fingerprint = hashlib.sha256(encoded).hexdigest()
    required = [capability for capability in _CAPABILITIES if capability["required_for_draft"]]
    unverified_required = [
        capability["key"] for capability in required if capability["status"] != "verified"
    ]
    return {
        **contract,
        "contract_fingerprint": fingerprint,
        "source": "repository_evidence",
        "can_execute_draft": not unverified_required,
        "manual_handoff_available": True,
        "unverified_required_capabilities": unverified_required,
    }
