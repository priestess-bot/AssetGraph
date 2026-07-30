from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

from app.services.functional_operation_imports import FunctionalOperationImportService


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured"
)


def test_file_import_requires_preview_then_preserves_pending_binding_and_source() -> None:
    suffix = uuid4().hex
    external_id = f"file-import-{suffix}"
    csv_content = (
        "场次名称,平台,外部场次ID,来源时区,场次开始时间,场次结束时间,内容类型,内容编码,"
        "指标名称,指标数值,指标单位,指标来源时钟,时钟偏移毫秒,时钟漂移PPM,"
        "对齐覆盖开始毫秒,对齐覆盖结束毫秒,来源证据备注\n"
        f"文件导入场次,douyin,{external_id},Asia/Shanghai,2026-07-26T20:00:00+08:00,"
        "2026-07-26T20:30:00+08:00,live_room_plan,LIVEPLAN-NOT-FOUND,watchers,120,person,"
        "recording_elapsed_ms,0,0,0,1800000,脱敏测试文件\n"
    ).encode("utf-8")

    with psycopg.connect(DATABASE_URL) as connection:
        service = FunctionalOperationImportService(connection)
        preview = service.preview(f"operations-{suffix}.csv", csv_content, "tester")

        assert preview["status"] == "preview"
        assert preview["preview_summary"]["pending_binding_row_count"] == 1
        assert preview["rows"][0]["import_status"] == "pending_binding"
        assert service.source_file(preview["batch_code"])[0] == csv_content

        confirmed = service.confirm(preview["batch_code"], "tester")
        assert confirmed["status"] == "confirmed"
        assert confirmed["preview_summary"]["pending_session_count"] == 1
        session_code = confirmed["rows"][0]["imported_session_code"]

        pending = service.pending_bindings()
        pending_row = next(row for row in pending if row["session_code"] == session_code)
        assert pending_row["content_code"] == "LIVEPLAN-NOT-FOUND"
        assert pending_row["revision_number"] == 1

        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT binding_status, metrics, source_evidence
                   FROM functional_operation_sessions WHERE session_code = %s""",
                (session_code,),
            )
            session = cursor.fetchone()
            assert session[0] == "pending"
            assert session[1] == {"watchers": 120.0}
            assert session[2]["batch_code"] == preview["batch_code"]
            cursor.execute(
                """SELECT source_clock, coverage_end_ms
                   FROM functional_session_time_mappings WHERE session_code = %s""",
                (session_code,),
            )
            assert cursor.fetchone() == ("recording_elapsed_ms", 1_800_000)

        duplicate = service.preview(
            f"operations-replay-{suffix}.csv", csv_content, "tester"
        )
        assert duplicate["preview_summary"]["duplicate_row_count"] == 1
        assert duplicate["rows"][0]["duplicate_of_session_code"] == session_code
