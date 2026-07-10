from datetime import date
from enum import StrEnum


class AssetType(StrEnum):
    IMAGE = "IMG"
    VIDEO = "VID"
    AUDIO = "AUD"
    DOCUMENT = "DOC"
    OTHER = "OTH"


class BusinessObjectType(StrEnum):
    DIGITAL_HUMAN = "DH"
    VOICE_PROFILE = "VOICE"
    PRODUCT = "PROD"
    SCRIPT = "SCRIPT"
    VIDEO_SEGMENT = "SEG"
    MAITU_SLOT = "MT-SLOT"
    MAITU_PLAN = "MT-PLAN"
    MAITU_BUILD_PLAN = "MT-BUILD"
    MAITU_LAYOUT_ADJUSTMENT = "MT-ADJ"
    MAITU_EXECUTION = "MT-EXEC"
    MAITU_RETRY_TASK = "MT-RETRY"
    JD_LIVE_METRIC_SESSION = "JD-METRIC"

ASSET_CODE_PREFIX = "AG"
LIVE_CODE_PREFIX = "AG-LIVE"
MAITU_SLOT_CODE_PREFIX = "MT-SLOT"
MAITU_PLAN_CODE_PREFIX = "MT-PLAN"
MAITU_BUILD_PLAN_CODE_PREFIX = "MT-BUILD"
MAITU_LAYOUT_ADJUSTMENT_CODE_PREFIX = "MT-ADJ"
MAITU_EXECUTION_CODE_PREFIX = "MT-EXEC"
MAITU_RETRY_TASK_CODE_PREFIX = "MT-RETRY"
JD_LIVE_METRIC_SESSION_CODE_PREFIX = "JD-METRIC"



def _validate_sequence(sequence: int) -> None:
    if sequence < 1:
        raise ValueError("sequence must be positive")


def format_asset_code(asset_type: AssetType | str, sequence_date: date, sequence: int) -> str:
    _validate_sequence(sequence)
    normalized_type = AssetType(asset_type).value
    return f"{ASSET_CODE_PREFIX}-{normalized_type}-{sequence_date:%Y%m%d}-{sequence:06d}"


def format_live_code(sequence_date: date, sequence: int) -> str:
    _validate_sequence(sequence)
    return f"{LIVE_CODE_PREFIX}-{sequence_date:%Y%m%d}-{sequence:06d}"


def format_business_code(object_type: BusinessObjectType | str, sequence_date: date, sequence: int) -> str:
    _validate_sequence(sequence)
    normalized_type = BusinessObjectType(object_type).value
    return f"{ASSET_CODE_PREFIX}-{normalized_type}-{sequence_date:%Y%m%d}-{sequence:06d}"


def format_segment_code(sequence_date: date, sequence: int) -> str:
    return format_business_code(BusinessObjectType.VIDEO_SEGMENT, sequence_date, sequence)


def format_maitu_slot_code(sequence_date: date, sequence: int) -> str:
    _validate_sequence(sequence)
    return f"{MAITU_SLOT_CODE_PREFIX}-{sequence_date:%Y%m%d}-{sequence:06d}"


def format_maitu_plan_code(sequence_date: date, sequence: int) -> str:
    _validate_sequence(sequence)
    return f"{MAITU_PLAN_CODE_PREFIX}-{sequence_date:%Y%m%d}-{sequence:06d}"


def format_maitu_build_plan_code(sequence_date: date, sequence: int) -> str:
    _validate_sequence(sequence)
    return f"{MAITU_BUILD_PLAN_CODE_PREFIX}-{sequence_date:%Y%m%d}-{sequence:06d}"


def format_maitu_layout_adjustment_code(sequence_date: date, sequence: int) -> str:
    _validate_sequence(sequence)
    return f"{MAITU_LAYOUT_ADJUSTMENT_CODE_PREFIX}-{sequence_date:%Y%m%d}-{sequence:06d}"


def format_maitu_execution_code(sequence_date: date, sequence: int) -> str:
    _validate_sequence(sequence)
    return f"{MAITU_EXECUTION_CODE_PREFIX}-{sequence_date:%Y%m%d}-{sequence:06d}"


def format_maitu_retry_task_code(sequence_date: date, sequence: int) -> str:
    _validate_sequence(sequence)
    return f"{MAITU_RETRY_TASK_CODE_PREFIX}-{sequence_date:%Y%m%d}-{sequence:06d}"


def format_jd_live_metric_session_code(sequence_date: date, sequence: int) -> str:
    _validate_sequence(sequence)
    return f"{JD_LIVE_METRIC_SESSION_CODE_PREFIX}-{sequence_date:%Y%m%d}-{sequence:06d}"


class CodeGenerator:
    def next_asset_code(self, asset_type: AssetType | str, sequence_date: date, sequence: int) -> str:
        return format_asset_code(asset_type, sequence_date, sequence)

    def next_live_code(self, sequence_date: date, sequence: int) -> str:
        return format_live_code(sequence_date, sequence)

    def next_business_code(
        self,
        object_type: BusinessObjectType | str,
        sequence_date: date,
        sequence: int,
    ) -> str:
        return format_business_code(object_type, sequence_date, sequence)

    def next_segment_code(self, sequence_date: date, sequence: int) -> str:
        return format_segment_code(sequence_date, sequence)

    def next_maitu_slot_code(self, sequence_date: date, sequence: int) -> str:
        return format_maitu_slot_code(sequence_date, sequence)

    def next_maitu_plan_code(self, sequence_date: date, sequence: int) -> str:
        return format_maitu_plan_code(sequence_date, sequence)

    def next_maitu_build_plan_code(self, sequence_date: date, sequence: int) -> str:
        return format_maitu_build_plan_code(sequence_date, sequence)

    def next_maitu_layout_adjustment_code(self, sequence_date: date, sequence: int) -> str:
        return format_maitu_layout_adjustment_code(sequence_date, sequence)

    def next_maitu_execution_code(self, sequence_date: date, sequence: int) -> str:
        return format_maitu_execution_code(sequence_date, sequence)

    def next_maitu_retry_task_code(self, sequence_date: date, sequence: int) -> str:
        return format_maitu_retry_task_code(sequence_date, sequence)

    def next_jd_live_metric_session_code(self, sequence_date: date, sequence: int) -> str:
        return format_jd_live_metric_session_code(sequence_date, sequence)
