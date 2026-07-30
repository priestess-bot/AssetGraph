from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import zipfile
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import PurePath
from typing import Any
from xml.etree import ElementTree
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.contracts import canonical_fingerprint
from app.domain.errors import DomainValidationError
from app.services.functional_operations import FunctionalOperationsService


MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 5_000

TEMPLATE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("title", "场次名称"),
    ("platform", "平台"),
    ("external_session_id", "外部场次ID"),
    ("account_id", "账号主体"),
    ("target_resource_id", "直播间或渠道ID"),
    ("source_timezone", "来源时区"),
    ("started_at", "场次开始时间"),
    ("ended_at", "场次结束时间"),
    ("binding_kind", "内容类型"),
    ("binding_code", "内容编码"),
    ("binding_revision", "内容修订"),
    ("interval_scope_type", "区间对象类型"),
    ("interval_scope_code", "区间对象编码"),
    ("interval_start_ms", "区间开始毫秒"),
    ("interval_end_ms", "区间结束毫秒"),
    ("metric_key", "指标名称"),
    ("metric_value", "指标数值"),
    ("metric_unit", "指标单位"),
    ("metric_definition_code", "指标定义编码"),
    ("metric_definition_revision", "指标定义修订"),
    ("metric_source_clock", "指标来源时钟"),
    ("mapping_source_offset_ms", "时钟偏移毫秒"),
    ("mapping_drift_ppm", "时钟漂移PPM"),
    ("mapping_coverage_start_ms", "对齐覆盖开始毫秒"),
    ("mapping_coverage_end_ms", "对齐覆盖结束毫秒"),
    ("evidence_note", "来源证据备注"),
)

REQUIRED_COLUMNS = {
    "title",
    "platform",
    "external_session_id",
    "source_timezone",
    "started_at",
    "ended_at",
}

HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    canonical: (canonical, label) for canonical, label in TEMPLATE_COLUMNS
}
HEADER_ALIASES.update(
    {
        "title": (*HEADER_ALIASES["title"], "直播标题", "session_title"),
        "external_session_id": (
            *HEADER_ALIASES["external_session_id"],
            "场次ID",
            "session_id",
        ),
        "source_timezone": (*HEADER_ALIASES["source_timezone"], "时区", "timezone"),
        "started_at": (*HEADER_ALIASES["started_at"], "开始时间", "start_time"),
        "ended_at": (*HEADER_ALIASES["ended_at"], "结束时间", "end_time"),
        "binding_kind": (*HEADER_ALIASES["binding_kind"], "绑定类型"),
        "binding_code": (*HEADER_ALIASES["binding_code"], "绑定编码", "计划编码"),
        "binding_revision": (*HEADER_ALIASES["binding_revision"], "绑定修订"),
        "interval_scope_type": (*HEADER_ALIASES["interval_scope_type"], "区间类型"),
        "interval_scope_code": (*HEADER_ALIASES["interval_scope_code"], "场景或片段编码"),
        "metric_key": (*HEADER_ALIASES["metric_key"], "指标", "metric"),
        "metric_value": (*HEADER_ALIASES["metric_value"], "数值", "value"),
    }
)

EXAMPLE_ROWS: tuple[dict[str, object], ...] = (
    {
        "title": "夏日饮品晚场",
        "platform": "douyin",
        "external_session_id": "DY-20260726-001",
        "account_id": "brand-main",
        "target_resource_id": "room-10001",
        "source_timezone": "Asia/Shanghai",
        "started_at": "2026-07-26T20:00:00+08:00",
        "ended_at": "2026-07-26T20:30:00+08:00",
        "binding_kind": "live_room_plan",
        "binding_code": "LIVEPLAN-000001",
        "interval_scope_type": "maitu_scene",
        "interval_scope_code": "SCENE-OPENING",
        "interval_start_ms": 0,
        "interval_end_ms": 60000,
        "metric_key": "watchers",
        "metric_value": 1260,
        "metric_unit": "person",
        "metric_source_clock": "recording_elapsed_ms",
        "mapping_source_offset_ms": 0,
        "mapping_drift_ppm": 0,
        "mapping_coverage_start_ms": 0,
        "mapping_coverage_end_ms": 1800000,
        "evidence_note": "脱敏平台导出与人工场景校准",
    },
    {
        "title": "夏日饮品晚场",
        "platform": "douyin",
        "external_session_id": "DY-20260726-001",
        "account_id": "brand-main",
        "target_resource_id": "room-10001",
        "source_timezone": "Asia/Shanghai",
        "started_at": "2026-07-26T20:00:00+08:00",
        "ended_at": "2026-07-26T20:30:00+08:00",
        "binding_kind": "live_room_plan",
        "binding_code": "LIVEPLAN-000001",
        "interval_scope_type": "maitu_scene",
        "interval_scope_code": "SCENE-PRODUCT",
        "interval_start_ms": 60000,
        "interval_end_ms": 180000,
        "metric_key": "orders",
        "metric_value": 38,
        "metric_unit": "order",
        "metric_source_clock": "recording_elapsed_ms",
        "mapping_source_offset_ms": 0,
        "mapping_drift_ppm": 0,
        "mapping_coverage_start_ms": 0,
        "mapping_coverage_end_ms": 1800000,
        "evidence_note": "脱敏平台导出与人工场景校准",
    },
)


def _header_key(value: str) -> str:
    return re.sub(r"[\s_\-（）()\[\]【】/:]+", "", value.strip().lower())


ALIAS_LOOKUP = {
    _header_key(alias): canonical
    for canonical, aliases in HEADER_ALIASES.items()
    for alias in aliases
}


def operation_import_template_csv() -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=[label for _key, label in TEMPLATE_COLUMNS])
    writer.writeheader()
    for row in EXAMPLE_ROWS:
        writer.writerow(
            {label: row.get(canonical, "") for canonical, label in TEMPLATE_COLUMNS}
        )
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def _xlsx_column(index: int) -> str:
    result = ""
    value = index + 1
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def operation_import_template_xlsx() -> bytes:
    headers = [label for _key, label in TEMPLATE_COLUMNS]
    values = [headers]
    values.extend(
        [[str(row.get(key, "")) for key, _label in TEMPLATE_COLUMNS] for row in EXAMPLE_ROWS]
    )
    sheet_rows: list[str] = []
    for row_number, row in enumerate(values, start=1):
        cells = "".join(
            f'<c r="{_xlsx_column(index)}{row_number}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            for index, value in enumerate(row)
        )
        sheet_rows.append(f'<row r="{row_number}">{cells}</row>')
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:{_xlsx_column(len(headers) - 1)}{len(values)}"/>'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="运营数据" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>',
        )
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    return output.getvalue()


def _column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference.upper())
    if letters is None:
        return 0
    value = 0
    for letter in letters.group(0):
        value = value * 26 + ord(letter) - 64
    return value - 1


def _xlsx_rows(content: bytes) -> list[list[str]]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for info in archive.infolist():
                if info.file_size > 20 * 1024 * 1024:
                    raise DomainValidationError(
                        "OPERATION_IMPORT_XLSX_TOO_LARGE",
                        "XLSX 解压后的单个工作表过大。",
                    )
            shared: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                shared = [
                    "".join(node.text or "" for node in item.findall(".//x:t", namespace))
                    for item in root.findall("x:si", namespace)
                ]
            sheet_path = "xl/worksheets/sheet1.xml"
            if sheet_path not in archive.namelist():
                raise DomainValidationError(
                    "OPERATION_IMPORT_XLSX_SHEET_MISSING",
                    "XLSX 中没有可读取的第一个工作表。",
                )
            root = ElementTree.fromstring(archive.read(sheet_path))
    except (zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise DomainValidationError(
            "OPERATION_IMPORT_XLSX_INVALID", "XLSX 文件结构无效。"
        ) from exc
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rows: list[list[str]] = []
    for row in root.findall(".//x:sheetData/x:row", namespace):
        values: dict[int, str] = {}
        for cell in row.findall("x:c", namespace):
            index = _column_index(cell.attrib.get("r", "A1"))
            kind = cell.attrib.get("t")
            if kind == "inlineStr":
                value = "".join(
                    node.text or "" for node in cell.findall(".//x:t", namespace)
                )
            else:
                node = cell.find("x:v", namespace)
                value = node.text if node is not None and node.text is not None else ""
                if kind == "s" and value:
                    try:
                        value = shared[int(value)]
                    except (IndexError, ValueError):
                        value = ""
            values[index] = value
        width = max(values, default=-1) + 1
        rows.append([values.get(index, "") for index in range(width)])
    return rows


def read_operation_import_rows(content: bytes, file_kind: str) -> tuple[list[str], list[dict[str, str]]]:
    if file_kind == "csv":
        decoded: str | None = None
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                decoded = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if decoded is None:
            raise DomainValidationError(
                "OPERATION_IMPORT_CSV_ENCODING_INVALID",
                "CSV 必须使用 UTF-8 或 GB18030 编码。",
            )
        matrix = list(csv.reader(io.StringIO(decoded)))
    else:
        matrix = _xlsx_rows(content)
    while matrix and not any(value.strip() for value in matrix[-1]):
        matrix.pop()
    if not matrix:
        raise DomainValidationError("OPERATION_IMPORT_EMPTY", "导入文件没有数据。")
    headers = [value.strip() for value in matrix[0]]
    if not any(headers):
        raise DomainValidationError("OPERATION_IMPORT_HEADERS_MISSING", "导入文件缺少表头。")
    if len(matrix) - 1 > MAX_IMPORT_ROWS:
        raise DomainValidationError(
            "OPERATION_IMPORT_ROW_LIMIT",
            f"单个文件最多允许 {MAX_IMPORT_ROWS} 行。",
        )
    rows = [
        {
            header: (values[index].strip() if index < len(values) else "")
            for index, header in enumerate(headers)
            if header
        }
        for values in matrix[1:]
        if any(value.strip() for value in values)
    ]
    return headers, rows


def _parse_int(value: str, field: str, errors: list[dict[str, str]]) -> int | None:
    if not value.strip():
        return None
    try:
        number = float(value)
    except ValueError:
        errors.append({"field": field, "code": "NUMBER_INVALID", "message": "必须是数字。"})
        return None
    if not math.isfinite(number) or not number.is_integer():
        errors.append({"field": field, "code": "INTEGER_INVALID", "message": "必须是整数。"})
        return None
    return int(number)


def _parse_float(value: str, field: str, errors: list[dict[str, str]]) -> float | None:
    if not value.strip():
        return None
    try:
        number = float(value)
    except ValueError:
        errors.append({"field": field, "code": "NUMBER_INVALID", "message": "必须是数字。"})
        return None
    if not math.isfinite(number):
        errors.append({"field": field, "code": "NUMBER_INVALID", "message": "必须是有限数字。"})
        return None
    return number


def _parse_datetime(
    value: str,
    timezone_name: str,
    field: str,
    errors: list[dict[str, str]],
) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        errors.append(
            {
                "field": field,
                "code": "DATETIME_INVALID",
                "message": "请使用 ISO 8601 时间，例如 2026-07-26T20:00:00+08:00。",
            }
        )
        return None
    if parsed.tzinfo is None:
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
        except ZoneInfoNotFoundError:
            return None
    return parsed.astimezone(UTC)


def _mapped_values(raw: dict[str, str], field_mapping: dict[str, str]) -> dict[str, str]:
    result = {canonical: "" for canonical, _label in TEMPLATE_COLUMNS}
    for source, value in raw.items():
        canonical = field_mapping.get(source)
        if canonical:
            result[canonical] = value.strip()
    return result


def _normalize_row(raw: dict[str, str], field_mapping: dict[str, str]) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]]]:
    values = _mapped_values(raw, field_mapping)
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for field in REQUIRED_COLUMNS:
        if not values[field]:
            errors.append({"field": field, "code": "REQUIRED", "message": "此字段必填。"})
    timezone_name = values["source_timezone"] or "UTC"
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        errors.append(
            {
                "field": "source_timezone",
                "code": "TIMEZONE_INVALID",
                "message": "请使用 IANA 时区，例如 Asia/Shanghai。",
            }
        )
    started_at = _parse_datetime(values["started_at"], timezone_name, "started_at", errors) if values["started_at"] else None
    ended_at = _parse_datetime(values["ended_at"], timezone_name, "ended_at", errors) if values["ended_at"] else None
    if started_at and ended_at and ended_at <= started_at:
        errors.append(
            {
                "field": "ended_at",
                "code": "INTERVAL_INVALID",
                "message": "场次结束时间必须晚于开始时间。",
            }
        )
    duration_ms = round((ended_at - started_at).total_seconds() * 1000) if started_at and ended_at else None

    binding_kind = values["binding_kind"].lower()
    binding_code = values["binding_code"].strip()
    binding_revision = _parse_int(values["binding_revision"], "binding_revision", errors)
    allowed_binding_kinds = {"live_room_plan", "rendered_video_plan", "content_project_revision"}
    if binding_kind and binding_kind not in allowed_binding_kinds:
        errors.append(
            {
                "field": "binding_kind",
                "code": "BINDING_KIND_INVALID",
                "message": "内容类型只能是 live_room_plan、rendered_video_plan 或 content_project_revision。",
            }
        )
    if bool(binding_kind) != bool(binding_code):
        errors.append(
            {
                "field": "binding_code",
                "code": "BINDING_INCOMPLETE",
                "message": "内容类型和内容编码必须同时填写。",
            }
        )
    if binding_kind == "content_project_revision" and binding_code and not binding_revision:
        warnings.append(
            {
                "field": "binding_revision",
                "code": "REVISION_REQUIRED_FOR_EXACT_BINDING",
                "message": "内容项目未填写修订号，将进入待处理列表。",
            }
        )

    scope_type = values["interval_scope_type"].lower()
    scope_code = values["interval_scope_code"].strip()
    interval_start = _parse_int(values["interval_start_ms"], "interval_start_ms", errors)
    interval_end = _parse_int(values["interval_end_ms"], "interval_end_ms", errors)
    has_interval = any((scope_type, scope_code, values["interval_start_ms"], values["interval_end_ms"]))
    if has_interval:
        if not all((scope_type, scope_code, interval_start is not None, interval_end is not None)):
            errors.append(
                {
                    "field": "interval_scope_code",
                    "code": "INTERVAL_INCOMPLETE",
                    "message": "区间对象类型、编码、开始和结束毫秒必须一起填写。",
                }
            )
        elif interval_start < 0 or interval_end <= interval_start:
            errors.append(
                {
                    "field": "interval_end_ms",
                    "code": "INTERVAL_OFFSET_INVALID",
                    "message": "区间必须为非负且结束毫秒大于开始毫秒。",
                }
            )
        elif duration_ms is not None and interval_end > duration_ms:
            errors.append(
                {
                    "field": "interval_end_ms",
                    "code": "INTERVAL_OUTSIDE_SESSION",
                    "message": "内容区间不能超出场次时长。",
                }
            )
        if scope_type not in {"maitu_scene", "program_segment", "video_timeline_segment"}:
            errors.append(
                {
                    "field": "interval_scope_type",
                    "code": "SCOPE_TYPE_INVALID",
                    "message": "区间对象类型无效。",
                }
            )

    metric_key = values["metric_key"].strip()
    metric_value = _parse_float(values["metric_value"], "metric_value", errors)
    metric_revision = _parse_int(
        values["metric_definition_revision"], "metric_definition_revision", errors
    )
    if bool(metric_key) != bool(values["metric_value"]):
        errors.append(
            {
                "field": "metric_value",
                "code": "METRIC_INCOMPLETE",
                "message": "指标名称和数值必须同时填写。",
            }
        )
    metric_code = values["metric_definition_code"].strip()
    if bool(metric_code) != bool(metric_revision):
        errors.append(
            {
                "field": "metric_definition_code",
                "code": "METRIC_DEFINITION_INCOMPLETE",
                "message": "指标定义编码和修订必须同时填写。",
            }
        )

    source_clock = values["metric_source_clock"].strip() or "session_utc"
    offset_ms = _parse_int(values["mapping_source_offset_ms"], "mapping_source_offset_ms", errors)
    drift_ppm = _parse_float(values["mapping_drift_ppm"], "mapping_drift_ppm", errors)
    coverage_start = _parse_int(values["mapping_coverage_start_ms"], "mapping_coverage_start_ms", errors)
    coverage_end = _parse_int(values["mapping_coverage_end_ms"], "mapping_coverage_end_ms", errors)
    if source_clock != "session_utc":
        offset_ms = offset_ms if offset_ms is not None else 0
        drift_ppm = drift_ppm if drift_ppm is not None else 0.0
        coverage_start = coverage_start if coverage_start is not None else 0
        coverage_end = coverage_end if coverage_end is not None else duration_ms
        if coverage_end is None or coverage_end <= coverage_start or (duration_ms is not None and coverage_end > duration_ms):
            errors.append(
                {
                    "field": "mapping_coverage_end_ms",
                    "code": "MAPPING_COVERAGE_INVALID",
                    "message": "时钟对齐覆盖必须位于场次时长内。",
                }
            )

    normalized: dict[str, Any] = {
        "title": values["title"].strip(),
        "platform": values["platform"].strip().lower(),
        "external_session_id": values["external_session_id"].strip(),
        "account_id": values["account_id"].strip() or None,
        "target_resource_id": values["target_resource_id"].strip() or None,
        "source_timezone": timezone_name,
        "started_at": started_at.isoformat() if started_at else None,
        "ended_at": ended_at.isoformat() if ended_at else None,
        "binding": {
            "content_kind": binding_kind or None,
            "content_code": binding_code or None,
            "content_revision": binding_revision,
        },
        "interval": {
            "scope_type": scope_type,
            "scope_code": scope_code,
            "start_ms": interval_start,
            "end_ms": interval_end,
        }
        if has_interval
        else None,
        "metric": {
            "metric_key": metric_key,
            "value": metric_value,
            "unit": values["metric_unit"].strip() or None,
            "metric_code": metric_code or None,
            "revision_number": metric_revision,
            "source_clock": source_clock,
        }
        if metric_key
        else None,
        "time_mapping": {
            "source_clock": source_clock,
            "source_offset_ms": offset_ms,
            "drift_ppm": drift_ppm,
            "coverage_start_ms": coverage_start,
            "coverage_end_ms": coverage_end,
        }
        if source_clock != "session_utc"
        else None,
        "evidence_note": values["evidence_note"].strip() or "文件导入记录",
    }
    return normalized, errors, warnings


class FunctionalOperationImportService:
    def __init__(self, connection: Connection):
        self.connection = connection
        self.operations = FunctionalOperationsService(connection)

    @staticmethod
    def template(file_kind: str) -> tuple[bytes, str, str]:
        if file_kind == "csv":
            return operation_import_template_csv(), "text/csv; charset=utf-8", "assetgraph-operation-import-template.csv"
        if file_kind == "xlsx":
            return operation_import_template_xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "assetgraph-operation-import-template.xlsx"
        raise DomainValidationError(
            "OPERATION_IMPORT_FORMAT_UNSUPPORTED", "模板格式只能是 csv 或 xlsx。"
        )

    def preview(self, filename: str, content: bytes, actor: str) -> dict[str, Any]:
        if not content:
            raise DomainValidationError("OPERATION_IMPORT_EMPTY", "导入文件为空。")
        if len(content) > MAX_IMPORT_BYTES:
            raise DomainValidationError(
                "OPERATION_IMPORT_FILE_LIMIT", "导入文件不能超过 5 MB。"
            )
        suffix = PurePath(filename).suffix.lower().lstrip(".")
        if suffix not in {"csv", "xlsx"}:
            raise DomainValidationError(
                "OPERATION_IMPORT_FORMAT_UNSUPPORTED", "只支持 CSV 和 XLSX 文件。"
            )
        headers, raw_rows = read_operation_import_rows(content, suffix)
        field_mapping = {
            header: ALIAS_LOOKUP[_header_key(header)]
            for header in headers
            if _header_key(header) in ALIAS_LOOKUP
        }
        mapped_canonical = set(field_mapping.values())
        missing_columns = sorted(REQUIRED_COLUMNS - mapped_canonical)
        if missing_columns:
            labels = dict(TEMPLATE_COLUMNS)
            raise DomainValidationError(
                "OPERATION_IMPORT_REQUIRED_COLUMNS_MISSING",
                "缺少必需列：" + "、".join(labels[field] for field in missing_columns),
                details={"missing_columns": missing_columns, "field_mapping": field_mapping},
            )
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                rows: list[dict[str, Any]] = []
                seen_fingerprints: set[str] = set()
                sessions_in_file: dict[tuple[str, str], dict[str, Any]] = {}
                for row_number, raw in enumerate(raw_rows, start=2):
                    normalized, errors, warnings = _normalize_row(raw, field_mapping)
                    fingerprint = canonical_fingerprint(normalized)
                    duplicate_kind = None
                    duplicate_session = None
                    if fingerprint in seen_fingerprints:
                        duplicate_kind = "exact_file_row"
                    seen_fingerprints.add(fingerprint)
                    identity = (
                        str(normalized.get("platform") or ""),
                        str(normalized.get("external_session_id") or ""),
                    )
                    if all(identity):
                        base = {
                            key: normalized.get(key)
                            for key in (
                                "title",
                                "platform",
                                "external_session_id",
                                "account_id",
                                "target_resource_id",
                                "source_timezone",
                                "started_at",
                                "ended_at",
                                "binding",
                                "time_mapping",
                            )
                        }
                        previous = sessions_in_file.get(identity)
                        if previous is None:
                            sessions_in_file[identity] = base
                        elif previous != base:
                            errors.append(
                                {
                                    "field": "external_session_id",
                                    "code": "SESSION_ROWS_CONFLICT",
                                    "message": "同一外部场次 ID 的基础字段或绑定不一致。",
                                }
                            )
                        cursor.execute(
                            "SELECT session_code FROM functional_operation_sessions WHERE platform = %s AND external_session_id = %s",
                            identity,
                        )
                        existing = cursor.fetchone()
                        if existing is not None:
                            duplicate_kind = "existing_session"
                            duplicate_session = existing["session_code"]
                    binding = normalized.get("binding") or {}
                    resolution = self._resolve_binding(
                        cursor,
                        binding.get("content_kind"),
                        binding.get("content_code"),
                        binding.get("content_revision"),
                    )
                    binding_status = resolution["status"]
                    candidates = resolution["candidates"]
                    if binding_status == "pending":
                        warnings.append(
                            {
                                "field": "binding_code",
                                "code": "CONTENT_BINDING_PENDING",
                                "message": "未找到精确内容修订；确认后场次会进入待处理列表。",
                            }
                        )
                    if errors:
                        import_status = "invalid"
                    elif duplicate_kind:
                        import_status = "duplicate"
                    elif binding_status == "pending":
                        import_status = "pending_binding"
                    else:
                        import_status = "ready"
                    rows.append(
                        {
                            "row_number": row_number,
                            "row_fingerprint_sha256": fingerprint,
                            "raw_values": raw,
                            "normalized_payload": normalized,
                            "validation_errors": errors,
                            "validation_warnings": warnings,
                            "duplicate_kind": duplicate_kind,
                            "duplicate_of_session_code": duplicate_session,
                            "binding_status": binding_status,
                            "binding_candidates": candidates,
                            "import_status": import_status,
                        }
                    )
                self._validate_group_metrics_and_intervals(rows)
                for row in rows:
                    if row["validation_errors"]:
                        row["import_status"] = "invalid"
                summary = self._summary(rows)
                batch_code = self.operations._next(
                    cursor, "OPS-IMPORT", "functional_operation_import_batch"
                )
                cursor.execute(
                    """INSERT INTO functional_operation_import_batches
                       (batch_code,original_filename,file_kind,source_checksum_sha256,source_file,
                        field_mapping,preview_summary,created_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (
                        batch_code,
                        PurePath(filename).name[:255],
                        suffix,
                        hashlib.sha256(content).hexdigest(),
                        content,
                        Jsonb(field_mapping),
                        Jsonb(summary),
                        actor.strip(),
                    ),
                )
                batch = dict(cursor.fetchone())
                for row in rows:
                    cursor.execute(
                        """INSERT INTO functional_operation_import_rows
                           (batch_id,row_number,row_fingerprint_sha256,raw_values,normalized_payload,
                            validation_errors,validation_warnings,duplicate_kind,duplicate_of_session_code,
                            binding_status,binding_candidates,import_status)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            batch["id"],
                            row["row_number"],
                            row["row_fingerprint_sha256"],
                            Jsonb(row["raw_values"]),
                            Jsonb(row["normalized_payload"]),
                            Jsonb(row["validation_errors"]),
                            Jsonb(row["validation_warnings"]),
                            row["duplicate_kind"],
                            row["duplicate_of_session_code"],
                            row["binding_status"],
                            Jsonb(row["binding_candidates"]),
                            row["import_status"],
                        ),
                    )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get(batch_code) or batch

    @staticmethod
    def _validate_group_metrics_and_intervals(rows: list[dict[str, Any]]) -> None:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            payload = row["normalized_payload"]
            grouped[(str(payload.get("platform") or ""), str(payload.get("external_session_id") or ""))].append(row)
        for group in grouped.values():
            metrics: dict[str, float] = {}
            intervals: list[tuple[int, int, int]] = []
            for row in group:
                metric = row["normalized_payload"].get("metric")
                if isinstance(metric, dict) and metric.get("metric_key") and metric.get("value") is not None:
                    key = str(metric["metric_key"])
                    value = float(metric["value"])
                    if key in metrics and metrics[key] != value:
                        row["validation_errors"].append(
                            {
                                "field": "metric_value",
                                "code": "METRIC_VALUE_CONFLICT",
                                "message": f"同一场次的指标 {key} 出现不同数值。",
                            }
                        )
                    metrics[key] = value
                interval = row["normalized_payload"].get("interval")
                if isinstance(interval, dict) and interval.get("start_ms") is not None and interval.get("end_ms") is not None:
                    start = int(interval["start_ms"])
                    end = int(interval["end_ms"])
                    for previous_start, previous_end, previous_row in intervals:
                        if start < previous_end and end > previous_start:
                            row["validation_errors"].append(
                                {
                                    "field": "interval_start_ms",
                                    "code": "INTERVAL_OVERLAP",
                                    "message": f"内容区间与第 {previous_row} 行重叠。",
                                }
                            )
                    intervals.append((start, end, row["row_number"]))

    @staticmethod
    def _summary(rows: list[dict[str, Any]]) -> dict[str, int]:
        session_keys = {
            (
                str(row["normalized_payload"].get("platform") or ""),
                str(row["normalized_payload"].get("external_session_id") or ""),
            )
            for row in rows
            if row["normalized_payload"].get("external_session_id")
        }
        counts = {status: 0 for status in ("ready", "pending_binding", "invalid", "duplicate")}
        for row in rows:
            if row["import_status"] in counts:
                counts[row["import_status"]] += 1
        return {
            "row_count": len(rows),
            "session_count": len(session_keys),
            "ready_row_count": counts["ready"],
            "pending_binding_row_count": counts["pending_binding"],
            "invalid_row_count": counts["invalid"],
            "duplicate_row_count": counts["duplicate"],
        }

    def _resolve_binding(
        self,
        cursor: Any,
        content_kind: str | None,
        content_code: str | None,
        content_revision: int | None,
    ) -> dict[str, Any]:
        if not content_kind or not content_code:
            return {
                "status": "pending",
                "content_kind": content_kind,
                "content_code": content_code,
                "content_revision": content_revision,
                "candidates": self._binding_candidates(cursor, content_kind),
            }
        row: dict[str, Any] | None = None
        if content_kind == "live_room_plan":
            cursor.execute(
                """SELECT plan.plan_code AS content_code, plan.project_code, plan.variant_code,
                          plan.release_code, plan.expected_title AS title,
                          variant.revision_number AS content_revision
                   FROM functional_live_room_plans AS plan
                   LEFT JOIN production_variant_revisions AS variant
                     ON variant.variant_code = plan.variant_code AND variant.status = 'confirmed'
                   WHERE plan.plan_code = %s""",
                (content_code,),
            )
            found = cursor.fetchone()
            row = dict(found) if found else None
        elif content_kind == "rendered_video_plan":
            cursor.execute(
                """SELECT plan.plan_code AS content_code, plan.project_code, plan.variant_code,
                          plan.release_code, plan.title, plan.timeline_revision AS content_revision
                   FROM functional_video_plans AS plan WHERE plan.plan_code = %s""",
                (content_code,),
            )
            found = cursor.fetchone()
            row = dict(found) if found else None
        elif content_kind == "content_project_revision" and content_revision:
            cursor.execute(
                """SELECT revision.project_code AS content_code, revision.revision_number AS content_revision,
                          revision.status, project.title, revision.project_code
                   FROM content_project_revisions AS revision
                   JOIN content_projects AS project ON project.id = revision.project_id
                   WHERE revision.project_code = %s AND revision.revision_number = %s""",
                (content_code, content_revision),
            )
            found = cursor.fetchone()
            row = dict(found) if found else None
        if row is None:
            return {
                "status": "pending",
                "content_kind": content_kind,
                "content_code": content_code,
                "content_revision": content_revision,
                "candidates": self._binding_candidates(cursor, content_kind, content_code),
            }
        row.update({"status": "resolved", "content_kind": content_kind, "candidates": []})
        return row

    @staticmethod
    def _binding_candidates(cursor: Any, content_kind: str | None, query: str | None = None) -> list[dict[str, Any]]:
        pattern = f"%{query or ''}%"
        if content_kind == "live_room_plan":
            cursor.execute(
                """SELECT plan_code AS content_code, expected_title AS title, NULL::integer AS content_revision
                   FROM functional_live_room_plans
                   WHERE plan_code ILIKE %s OR expected_title ILIKE %s
                   ORDER BY updated_at DESC LIMIT 5""",
                (pattern, pattern),
            )
        elif content_kind == "rendered_video_plan":
            cursor.execute(
                """SELECT plan_code AS content_code, title, timeline_revision AS content_revision
                   FROM functional_video_plans
                   WHERE plan_code ILIKE %s OR title ILIKE %s
                   ORDER BY updated_at DESC LIMIT 5""",
                (pattern, pattern),
            )
        else:
            cursor.execute(
                """SELECT revision.project_code AS content_code, project.title,
                          revision.revision_number AS content_revision
                   FROM content_project_revisions AS revision
                   JOIN content_projects AS project ON project.id = revision.project_id
                   WHERE revision.project_code ILIKE %s OR project.title ILIKE %s
                   ORDER BY revision.created_at DESC LIMIT 5""",
                (pattern, pattern),
            )
            content_kind = "content_project_revision"
        return [
            {**dict(row), "content_kind": content_kind}
            for row in cursor.fetchall()
        ]

    def list(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT batch_code FROM functional_operation_import_batches ORDER BY created_at DESC"
            )
            codes = [row["batch_code"] for row in cursor.fetchall()]
        return [batch for code in codes if (batch := self.get(code)) is not None]

    def get(self, batch_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM functional_operation_import_batches WHERE batch_code = %s",
                (batch_code,),
            )
            batch = cursor.fetchone()
            if batch is None:
                return None
            cursor.execute(
                """SELECT row_number,row_fingerprint_sha256,raw_values,normalized_payload,
                          validation_errors,validation_warnings,duplicate_kind,
                          duplicate_of_session_code,binding_status,binding_candidates,
                          import_status,imported_session_code,created_at
                   FROM functional_operation_import_rows
                   WHERE batch_id = %s ORDER BY row_number""",
                (batch["id"],),
            )
            rows = [dict(row) for row in cursor.fetchall()]
        result = dict(batch)
        result.pop("source_file", None)
        result["rows"] = rows
        return result

    def source_file(self, batch_code: str) -> tuple[bytes, str, str] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT source_file, original_filename, file_kind
                   FROM functional_operation_import_batches WHERE batch_code = %s""",
                (batch_code,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        media_type = "text/csv; charset=utf-8" if row["file_kind"] == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return bytes(row["source_file"]), media_type, row["original_filename"]

    def confirm(self, batch_code: str, actor: str) -> dict[str, Any]:
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT * FROM functional_operation_import_batches WHERE batch_code = %s FOR UPDATE",
                    (batch_code,),
                )
                batch = cursor.fetchone()
                if batch is None:
                    raise DomainValidationError(
                        "OPERATION_IMPORT_BATCH_NOT_FOUND", "导入批次不存在。"
                    )
                if batch["status"] == "confirmed":
                    self.connection.rollback()
                    return self.get(batch_code) or dict(batch)
                cursor.execute(
                    """SELECT * FROM functional_operation_import_rows
                       WHERE batch_id = %s ORDER BY row_number FOR UPDATE""",
                    (batch["id"],),
                )
                rows = [dict(row) for row in cursor.fetchall()]
                importable = [
                    row
                    for row in rows
                    if row["import_status"] in {"ready", "pending_binding"}
                ]
                if not importable:
                    raise DomainValidationError(
                        "OPERATION_IMPORT_NO_VALID_ROWS",
                        "没有可以确认入库的行；请修复错误或重复数据后重新上传。",
                    )
                grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
                for row in importable:
                    payload = row["normalized_payload"]
                    grouped[(payload["platform"], payload["external_session_id"])].append(row)
                imported_sessions = 0
                pending_sessions = 0
                for identity, group in grouped.items():
                    cursor.execute(
                        "SELECT session_code FROM functional_operation_sessions WHERE platform = %s AND external_session_id = %s",
                        identity,
                    )
                    existing = cursor.fetchone()
                    if existing:
                        cursor.execute(
                            """UPDATE functional_operation_import_rows
                               SET import_status = 'skipped', duplicate_kind = 'existing_session',
                                   duplicate_of_session_code = %s, imported_session_code = %s
                               WHERE id = ANY(%s)""",
                            (
                                existing["session_code"],
                                existing["session_code"],
                                [row["id"] for row in group],
                            ),
                        )
                        continue
                    payload = dict(group[0]["normalized_payload"])
                    binding_input = payload.get("binding") or {}
                    binding = self._resolve_binding(
                        cursor,
                        binding_input.get("content_kind"),
                        binding_input.get("content_code"),
                        binding_input.get("content_revision"),
                    )
                    metrics: dict[str, float] = {}
                    metric_refs: list[dict[str, Any]] = []
                    for item in group:
                        metric = item["normalized_payload"].get("metric")
                        if not isinstance(metric, dict) or not metric.get("metric_key"):
                            continue
                        metrics[str(metric["metric_key"])] = float(metric["value"])
                        if metric.get("metric_code") and metric.get("revision_number"):
                            metric_refs.append(
                                {
                                    "metric_key": metric["metric_key"],
                                    "metric_code": metric["metric_code"],
                                    "revision_number": int(metric["revision_number"]),
                                }
                            )
                    metric_refs = self.operations._resolve_metric_definition_refs(
                        cursor,
                        {"metrics": metrics, "metric_definition_refs": metric_refs},
                    )
                    session_code = self.operations._next(
                        cursor, "OPS", "functional_operation_session"
                    )
                    source_evidence = {
                        "kind": "operation_file_import",
                        "batch_code": batch_code,
                        "original_filename": batch["original_filename"],
                        "source_checksum_sha256": batch["source_checksum_sha256"],
                        "row_numbers": [row["row_number"] for row in group],
                    }
                    cursor.execute(
                        """INSERT INTO functional_operation_sessions
                           (session_code,title,platform,external_session_id,account_id,target_resource_id,
                            source_timezone,source_evidence,content_project_code,live_room_plan_code,
                            video_plan_code,variant_code,release_code,bound_content_kind,bound_content_code,
                            bound_content_revision,binding_status,started_at,ended_at,metrics,
                            metric_definition_refs,source_kind)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'manual_import')
                           RETURNING *""",
                        (
                            session_code,
                            payload["title"],
                            payload["platform"],
                            payload["external_session_id"],
                            payload.get("account_id"),
                            payload.get("target_resource_id"),
                            payload["source_timezone"],
                            Jsonb(source_evidence),
                            binding.get("project_code")
                            or (
                                binding.get("content_code")
                                if binding.get("content_kind") == "content_project_revision"
                                else None
                            ),
                            binding.get("content_code")
                            if binding.get("status") == "resolved"
                            and binding.get("content_kind") == "live_room_plan"
                            else None,
                            binding.get("content_code")
                            if binding.get("status") == "resolved"
                            and binding.get("content_kind") == "rendered_video_plan"
                            else None,
                            binding.get("variant_code"),
                            binding.get("release_code"),
                            binding.get("content_kind"),
                            binding.get("content_code"),
                            binding.get("content_revision"),
                            binding["status"],
                            datetime.fromisoformat(payload["started_at"]),
                            datetime.fromisoformat(payload["ended_at"]),
                            Jsonb(metrics),
                            Jsonb(metric_refs),
                        ),
                    )
                    session = dict(cursor.fetchone())
                    self._insert_binding_revision(
                        cursor,
                        session,
                        binding,
                        actor=actor,
                        evidence_note=f"由导入批次 {batch_code} 建立。",
                        batch_code=batch_code,
                    )
                    self._insert_time_mapping(cursor, session, group, actor)
                    if binding["status"] == "resolved":
                        self._insert_intervals(cursor, session, binding, group)
                        imported_sessions += 1
                    else:
                        pending_sessions += 1
                    cursor.execute(
                        """UPDATE functional_operation_import_rows
                           SET import_status = 'imported', imported_session_code = %s,
                               binding_status = %s, binding_candidates = %s
                           WHERE id = ANY(%s)""",
                        (
                            session_code,
                            binding["status"],
                            Jsonb(binding.get("candidates") or []),
                            [row["id"] for row in group],
                        ),
                    )
                confirmed_summary = dict(batch["preview_summary"] or {})
                confirmed_summary.update(
                    {
                        "imported_session_count": imported_sessions + pending_sessions,
                        "resolved_session_count": imported_sessions,
                        "pending_session_count": pending_sessions,
                    }
                )
                cursor.execute(
                    """UPDATE functional_operation_import_batches
                       SET status = 'confirmed', confirmed_by = %s, confirmed_at = now(),
                           preview_summary = %s
                       WHERE id = %s""",
                    (actor.strip(), Jsonb(confirmed_summary), batch["id"]),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get(batch_code) or {}

    def _insert_binding_revision(
        self,
        cursor: Any,
        session: dict[str, Any],
        binding: dict[str, Any],
        *,
        actor: str,
        evidence_note: str,
        batch_code: str | None,
        revision_number: int = 1,
    ) -> dict[str, Any]:
        binding_code = self.operations._next(
            cursor, "OPS-BIND", "functional_operation_session_binding"
        )
        cursor.execute(
            """INSERT INTO functional_operation_session_bindings
               (binding_code,session_id,session_code,revision_number,resolution_status,
                content_kind,content_code,content_revision,candidates,source_import_batch_code,
                evidence_note,actor)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (
                binding_code,
                session["id"],
                session["session_code"],
                revision_number,
                binding["status"],
                binding.get("content_kind"),
                binding.get("content_code"),
                binding.get("content_revision"),
                Jsonb(binding.get("candidates") or []),
                batch_code,
                evidence_note.strip(),
                actor.strip(),
            ),
        )
        return dict(cursor.fetchone())

    def _insert_time_mapping(
        self, cursor: Any, session: dict[str, Any], rows: list[dict[str, Any]], actor: str
    ) -> None:
        mappings = [
            row["normalized_payload"].get("time_mapping")
            for row in rows
            if row["normalized_payload"].get("time_mapping")
        ]
        if not mappings:
            return
        mapping = mappings[0]
        if any(item != mapping for item in mappings[1:]):
            raise DomainValidationError(
                "OPERATION_IMPORT_MAPPING_CONFLICT",
                "同一场次包含不一致的 TimeMapping。",
            )
        code = self.operations._next(
            cursor, "TIME-MAP", "functional_session_time_mapping"
        )
        cursor.execute(
            """INSERT INTO functional_session_time_mappings
               (mapping_code,session_id,session_code,revision_number,status,source_clock,
                source_kind,source_offset_ms,drift_ppm,coverage_start_ms,coverage_end_ms,
                evidence_note,actor)
               VALUES (%s,%s,%s,1,'active',%s,'platform_anchor',%s,%s,%s,%s,%s,%s)""",
            (
                code,
                session["id"],
                session["session_code"],
                mapping["source_clock"],
                mapping["source_offset_ms"],
                mapping["drift_ppm"],
                mapping["coverage_start_ms"],
                mapping["coverage_end_ms"],
                f"由运营导入文件建立；来源时钟 {mapping['source_clock']}。",
                actor.strip(),
            ),
        )

    def _insert_intervals(
        self,
        cursor: Any,
        session: dict[str, Any],
        binding: dict[str, Any],
        rows: list[dict[str, Any]],
    ) -> None:
        for row in rows:
            interval = row["normalized_payload"].get("interval")
            if not isinstance(interval, dict):
                continue
            self._validate_interval_scope(cursor, binding, interval)
            exposure_code = self.operations._next(
                cursor, "EXPOSURE", "functional_content_exposure"
            )
            start = session["started_at"] + timedelta(milliseconds=int(interval["start_ms"]))
            end = session["started_at"] + timedelta(milliseconds=int(interval["end_ms"]))
            cursor.execute(
                """INSERT INTO functional_content_exposures
                   (exposure_code,session_id,session_code,plan_code,variant_code,release_code,
                    scene_code,started_at,ended_at,source_kind,evidence_note,confidence,
                    content_kind,content_code,content_revision,scope_type,scope_code)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'served_log',%s,1,%s,%s,%s,%s,%s)""",
                (
                    exposure_code,
                    session["id"],
                    session["session_code"],
                    binding["content_code"],
                    binding.get("variant_code") or binding["content_code"],
                    binding.get("release_code"),
                    interval["scope_code"],
                    start,
                    end,
                    row["normalized_payload"].get("evidence_note") or "文件导入区间",
                    binding["content_kind"],
                    binding["content_code"],
                    binding.get("content_revision"),
                    interval["scope_type"],
                    interval["scope_code"],
                ),
            )

    @staticmethod
    def _validate_interval_scope(cursor: Any, binding: dict[str, Any], interval: dict[str, Any]) -> None:
        kind = binding["content_kind"]
        scope_type = interval["scope_type"]
        scope_code = interval["scope_code"]
        found = False
        if kind == "live_room_plan" and scope_type == "maitu_scene":
            cursor.execute(
                "SELECT blueprint FROM functional_live_room_plans WHERE plan_code = %s",
                (binding["content_code"],),
            )
            row = cursor.fetchone()
            found = bool(
                row
                and any(
                    isinstance(scene, dict) and scene.get("scene_code") == scope_code
                    for scene in (row["blueprint"] or {}).get("scenes") or []
                )
            )
        elif kind == "rendered_video_plan" and scope_type == "video_timeline_segment":
            cursor.execute(
                """SELECT 1 FROM functional_video_timeline_segments AS segment
                   JOIN functional_video_plans AS plan ON plan.id = segment.plan_id
                   WHERE plan.plan_code = %s AND segment.timeline_revision = plan.timeline_revision
                     AND segment.segment_code = %s""",
                (binding["content_code"], scope_code),
            )
            found = cursor.fetchone() is not None
        elif kind == "content_project_revision" and scope_type == "program_segment":
            cursor.execute(
                """SELECT 1 FROM program_segments AS segment
                   JOIN content_program_revisions AS program ON program.id = segment.program_revision_id
                   JOIN content_projects AS project ON project.id = program.project_id
                   WHERE project.project_code = %s AND segment.segment_code = %s""",
                (binding["content_code"], scope_code),
            )
            found = cursor.fetchone() is not None
        if not found:
            raise DomainValidationError(
                "OPERATION_IMPORT_INTERVAL_SCOPE_NOT_FOUND",
                f"区间对象 {scope_type}:{scope_code} 不属于绑定内容。",
            )

    def pending_bindings(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT session.session_code, session.title, session.platform,
                          session.external_session_id, session.started_at, session.ended_at,
                          binding.binding_code, binding.revision_number, binding.content_kind,
                          binding.content_code, binding.content_revision, binding.candidates,
                          binding.evidence_note, binding.created_at
                   FROM functional_operation_sessions AS session
                   JOIN functional_operation_session_bindings AS binding
                     ON binding.session_id = session.id AND binding.status = 'active'
                   WHERE binding.resolution_status = 'pending'
                   ORDER BY session.started_at DESC"""
            )
            return [dict(row) for row in cursor.fetchall()]

    def resolve_session_binding(
        self, session_code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT * FROM functional_operation_sessions WHERE session_code = %s FOR UPDATE",
                    (session_code,),
                )
                session = cursor.fetchone()
                if session is None:
                    raise DomainValidationError(
                        "OPERATION_SESSION_NOT_FOUND", "运营场次不存在。"
                    )
                cursor.execute(
                    """SELECT * FROM functional_operation_session_bindings
                       WHERE session_id = %s AND status = 'active' FOR UPDATE""",
                    (session["id"],),
                )
                current = cursor.fetchone()
                current_revision = int(current["revision_number"]) if current else 0
                if payload["expected_revision"] != current_revision:
                    raise DomainValidationError(
                        "OPERATION_BINDING_REVISION_CONFLICT",
                        "内容绑定已经变化，请刷新后重试。",
                        details={"expected_revision": payload["expected_revision"], "actual_revision": current_revision},
                    )
                resolved = self._resolve_binding(
                    cursor,
                    payload["content_kind"],
                    payload["content_code"],
                    payload.get("content_revision"),
                )
                if resolved["status"] != "resolved":
                    raise DomainValidationError(
                        "OPERATION_BINDING_TARGET_NOT_FOUND",
                        "选择的内容修订不存在。",
                        details={"candidates": resolved.get("candidates") or []},
                    )
                if current:
                    cursor.execute(
                        "UPDATE functional_operation_session_bindings SET status = 'superseded' WHERE id = %s",
                        (current["id"],),
                    )
                cursor.execute(
                    """UPDATE functional_content_exposures
                       SET status = 'retracted', correction_reason = %s
                       WHERE session_id = %s AND status = 'active'""",
                    (payload["evidence_note"].strip(), session["id"]),
                )
                cursor.execute(
                    """UPDATE functional_operation_sessions
                       SET content_project_code = %s, live_room_plan_code = %s, video_plan_code = %s,
                           variant_code = %s, release_code = %s, bound_content_kind = %s,
                           bound_content_code = %s, bound_content_revision = %s,
                           binding_status = 'resolved', import_version = import_version + 1,
                           updated_at = now()
                       WHERE id = %s RETURNING *""",
                    (
                        resolved.get("project_code") or (
                            resolved["content_code"] if resolved["content_kind"] == "content_project_revision" else None
                        ),
                        resolved["content_code"] if resolved["content_kind"] == "live_room_plan" else None,
                        resolved["content_code"] if resolved["content_kind"] == "rendered_video_plan" else None,
                        resolved.get("variant_code"),
                        resolved.get("release_code"),
                        resolved["content_kind"],
                        resolved["content_code"],
                        resolved.get("content_revision"),
                        session["id"],
                    ),
                )
                updated_session = dict(cursor.fetchone())
                created = self._insert_binding_revision(
                    cursor,
                    updated_session,
                    resolved,
                    actor=payload["actor"],
                    evidence_note=payload["evidence_note"],
                    batch_code=current.get("source_import_batch_code") if current else None,
                    revision_number=current_revision + 1,
                )
                cursor.execute(
                    """SELECT row.* FROM functional_operation_import_rows AS row
                       WHERE row.imported_session_code = %s ORDER BY row.row_number""",
                    (session_code,),
                )
                source_rows = [dict(row) for row in cursor.fetchall()]
                self._insert_intervals(cursor, updated_session, resolved, source_rows)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return created
