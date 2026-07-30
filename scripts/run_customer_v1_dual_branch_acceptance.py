#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from psycopg import connect  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.repositories.assets import AssetRepository  # noqa: E402
from app.repositories.video_productions import VideoProductionRepository  # noqa: E402
from app.services.functional_content import FunctionalContentService  # noqa: E402
from app.services.functional_live_rooms import FunctionalLiveRoomService  # noqa: E402
from app.services.functional_videos import FunctionalVideoService  # noqa: E402
from app.services.video_production_pipeline import (  # noqa: E402
    DatabaseFinalAssetRegistrar,
    VideoProductionPipeline,
    VideoProductionWorker,
)
from app.services.video_production_tts import KokoroTTSClient  # noqa: E402


REQUIRED_ARTIFACTS = {"video", "poster", "contact_sheet", "subtitles", "render_manifest"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create and verify one customer-v1 live-room/video dual branch"
    )
    parser.add_argument(
        "--assets-root",
        type=Path,
        default=settings.asset_materials_root,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "outputs" / "customer-v1" / "v1-0515",
    )
    parser.add_argument(
        "--evidence-path",
        type=Path,
        default=REPO_ROOT / "docs" / "evidence" / "customer-v1-v1-0515-dual-branch.json",
    )
    parser.add_argument(
        "--tts-base-url",
        default="http://127.0.0.1:8020",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_live_room_asset(
    repository: AssetRepository,
    *,
    role: str,
    title: str,
) -> dict[str, Any]:
    return repository.create(
        {
            "asset_type": "IMG",
            "title": title,
            "original_filename": f"acceptance-{role}.png",
            "media_kind": "image",
            "material_roles": [role],
            "execution_capability": "maitu_bound",
            "rights_status": "approved",
            "rights_note": "Customer v1 local acceptance fixture",
            "description": "Customer-visible dual-branch acceptance fixture",
        }
    )


def public_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def variant_content_source(connection: Any, variant_code: str) -> dict[str, Any]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """SELECT project.project_code, project.revision_number
               FROM production_variant_revisions AS variant
               JOIN content_project_revisions AS project
                 ON project.id = variant.source_project_revision_id
               WHERE variant.variant_code = %s AND variant.status = 'confirmed'
               ORDER BY variant.revision_number DESC
               LIMIT 1""",
            (variant_code,),
        )
        source = cursor.fetchone()
    if source is None:
        raise RuntimeError(f"confirmed variant source is missing: {variant_code}")
    return dict(source)


def main() -> int:
    args = parse_args()
    assets_root = args.assets_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    evidence_path = args.evidence_path.expanduser().resolve()
    if not assets_root.is_dir():
        raise SystemExit(f"assets root does not exist: {assets_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    with connect(settings.postgres_dsn) as connection:
        content = FunctionalContentService(connection)
        project = content.create_project(
            {
                "title": "客户 V1 双分支验收 - 品酒大师 PRO",
                "generation_goal": "为夏日聚餐生成可审阅直播间方案和 30 秒竖屏商品介绍成片",
                "theme": "夏日聚餐的清爽红酒选择",
                "story": "从聚餐选酒问题切入，解释真实产品特点、饮用感受和搭餐建议。",
                "must_include": ["蛇龙珠", "橡木桶贮藏", "烤鸭和肉菜"],
                "must_avoid": ["未核实价格", "虚构优惠", "库存承诺"],
                "fact_card_codes": [],
                "secondary_template_codes": [],
                "target_duration_seconds": 30,
            },
            actor_id="customer-v1-acceptance",
        )
        content.confirm_project(
            project["project_code"],
            expected_revision=1,
            actor_id="customer-v1-acceptance",
        )
        content.parse_design_brief(
            project["project_code"],
            expected_revision=1,
            raw_input=(
                "Create one shared, confirmed content baseline for both a Maitu draft plan "
                "and a locally rendered vertical video. Never request go-live."
            ),
            actor_id="customer-v1-acceptance",
        )
        content.confirm_design_brief(
            project["project_code"],
            expected_revision=1,
            actor_id="customer-v1-acceptance",
        )
        generated = content.generate_chain(
            project["project_code"], actor_id="customer-v1-acceptance"
        )

        assets = AssetRepository(connection)
        live_assets = [
            create_live_room_asset(
                assets,
                role="digital_human",
                title="验收数字人占位",
            ),
            create_live_room_asset(
                assets,
                role="background",
                title="验收直播背景",
            ),
            create_live_room_asset(
                assets,
                role="promotion_text",
                title="验收商品信息层",
            ),
        ]
        live_plan = FunctionalLiveRoomService(connection).create_plan(
            {
                "project_code": generated["project_code"],
                "target_live_room_id": "customer-v1-empty-draft-001",
                "expected_title": "品酒大师 PRO 夏日聚餐验收直播间",
                "asset_codes": [asset["asset_code"] for asset in live_assets],
                "group_codes": [],
            },
            actor_id="customer-v1-acceptance",
        )
        video_service = FunctionalVideoService(connection)
        video_plan = video_service.create_plan(
            {
                "project_code": generated["project_code"],
                "title": "品酒大师 PRO 夏日聚餐 30 秒竖屏成片",
                "target_duration_seconds": 30,
            },
            actor_id="customer-v1-acceptance",
        )

        repository = VideoProductionRepository(connection)
        worker = VideoProductionWorker(
            repository=repository,
            pipeline=VideoProductionPipeline(
                assets_root=assets_root,
                output_root=output_root,
                tts=KokoroTTSClient(base_url=args.tts_base_url),
            ),
            final_asset_registrar=DatabaseFinalAssetRegistrar(assets),
            worker_id="customer-v1-acceptance-worker",
            lease_seconds=600,
            heartbeat_seconds=20,
        )
        if not worker.run_once():
            raise RuntimeError("video worker did not claim the acceptance job")
        rendered = video_service.get_plan(video_plan["plan_code"])
        if rendered is None:
            raise RuntimeError("rendered video plan disappeared")
        if rendered["job_status"] != "succeeded":
            raise RuntimeError(
                f"video production failed: {rendered.get('error_code')} {rendered.get('error_message')}"
            )

        artifact_by_key = {
            artifact["artifact_key"]: artifact for artifact in rendered["artifacts"]
        }
        missing = sorted(REQUIRED_ARTIFACTS - artifact_by_key.keys())
        if missing:
            raise RuntimeError(f"video production is missing artifacts: {', '.join(missing)}")
        artifact_evidence: list[dict[str, Any]] = []
        for key in sorted(REQUIRED_ARTIFACTS):
            artifact = artifact_by_key[key]
            path = output_root / str(artifact["relative_path"])
            if not path.is_file():
                raise RuntimeError(f"artifact file is missing: {key}")
            actual_checksum = sha256_file(path)
            if actual_checksum != artifact["checksum_sha256"]:
                raise RuntimeError(f"artifact checksum mismatch: {key}")
            artifact_evidence.append(
                {
                    "artifact_key": key,
                    "path": public_path(path),
                    "size_bytes": path.stat().st_size,
                    "checksum_sha256": actual_checksum,
                }
            )

        live_source = variant_content_source(connection, live_plan["variant_code"])
        video_source = variant_content_source(connection, rendered["variant_code"])
        shared_project = live_source["project_code"] == video_source["project_code"]
        shared_content_revision = (
            int(live_source["revision_number"]) == int(video_source["revision_number"])
        )
        if not shared_project or not shared_content_revision:
            raise RuntimeError("live-room and video branches do not share the confirmed content revision")
        if live_plan["build_plan"]["go_live"] is not False:
            raise RuntimeError("acceptance live-room BuildPlan must keep go_live=false")

        evidence = {
            "schema_version": "customer-v1-dual-branch-acceptance.v1",
            "created_at": datetime.now(UTC).isoformat(),
            "status": "passed",
            "content_project": {
                "project_code": generated["project_code"],
                "revision_number": generated["revision_number"],
                "story_brief_code": generated["story_brief"]["story_brief_code"],
                "script_revision_code": generated["script"]["script_revision_code"],
                "shot_list_revision_code": generated["shot_list"]["shot_list_revision_code"],
            },
            "live_room_branch": {
                "plan_code": live_plan["plan_code"],
                "variant_code": live_plan["variant_code"],
                "build_plan_code": live_plan["build_plan"]["build_plan_code"],
                "status": live_plan["status"],
                "scene_count": len(live_plan["blueprint"]["scenes"]),
                "go_live": live_plan["build_plan"]["go_live"],
                "target_live_room_id": live_plan["target_live_room_id"],
            },
            "video_branch": {
                "plan_code": rendered["plan_code"],
                "variant_code": rendered["variant_code"],
                "job_code": rendered["video_job_code"],
                "status": rendered["job_status"],
                "timeline_revision": rendered["timeline_revision"],
                "timeline_fingerprint_sha256": rendered["reproducibility"][
                    "timeline_fingerprint_sha256"
                ],
                "quality_passed": rendered["quality_report"].get("passed") is True,
                "artifacts": artifact_evidence,
            },
            "shared_revision_checks": {
                "same_project": shared_project,
                "same_content_project_revision": shared_content_revision,
            },
            "screenshots": [
                "docs/evidence/screenshots/customer-v1-v1-0515-live-room.png",
                "docs/evidence/screenshots/customer-v1-v1-0515-video.png",
            ],
            "boundaries": {
                "maitu_draft_write_executed": False,
                "go_live_requested": False,
                "video_rendering": "local Kokoro TTS plus FFmpeg",
            },
        }
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
