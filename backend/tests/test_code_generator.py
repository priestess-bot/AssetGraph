from datetime import date

import pytest

from app.services.code_generator import (
    BusinessObjectType,
    format_business_code,
    format_maitu_execution_code,
    format_maitu_plan_code,
    format_maitu_retry_task_code,
    format_maitu_slot_code,
    format_segment_code,
)


def test_format_digital_human_code() -> None:
    assert (
        format_business_code(BusinessObjectType.DIGITAL_HUMAN, date(2026, 7, 7), 1)
        == "AG-DH-20260707-000001"
    )


def test_format_voice_profile_code() -> None:
    assert (
        format_business_code(BusinessObjectType.VOICE_PROFILE, date(2026, 7, 7), 12)
        == "AG-VOICE-20260707-000012"
    )


def test_format_product_code() -> None:
    assert (
        format_business_code(BusinessObjectType.PRODUCT, date(2026, 7, 7), 123)
        == "AG-PROD-20260707-000123"
    )


def test_format_script_code() -> None:
    assert (
        format_business_code(BusinessObjectType.SCRIPT, date(2026, 7, 7), 2)
        == "AG-SCRIPT-20260707-000002"
    )


def test_format_video_segment_code() -> None:
    assert format_segment_code(date(2026, 7, 7), 3) == "AG-SEG-20260707-000003"


def test_format_maitu_slot_code() -> None:
    assert format_maitu_slot_code(date(2026, 7, 7), 4) == "MT-SLOT-20260707-000004"


def test_format_maitu_plan_code() -> None:
    assert format_maitu_plan_code(date(2026, 7, 7), 5) == "MT-PLAN-20260707-000005"


def test_format_maitu_execution_code() -> None:
    assert format_maitu_execution_code(date(2026, 7, 7), 6) == "MT-EXEC-20260707-000006"


def test_format_maitu_retry_task_code() -> None:
    assert format_maitu_retry_task_code(date(2026, 7, 7), 7) == "MT-RETRY-20260707-000007"


def test_business_code_rejects_zero_sequence() -> None:
    with pytest.raises(ValueError, match="sequence must be positive"):
        format_business_code(BusinessObjectType.PRODUCT, date(2026, 7, 7), 0)
