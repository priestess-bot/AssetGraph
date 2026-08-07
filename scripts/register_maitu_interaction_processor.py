#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from psycopg import connect  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.domain.contracts import DataClassification  # noqa: E402
from app.repositories.privacy_governance import PrivacyGovernanceRepository  # noqa: E402
from app.services.maitu_interactions import (  # noqa: E402
    INTERACTION_PROCESSING_PURPOSE,
    INTERACTION_PROCESSOR_FIELDS,
)
from app.services.content_workflow import (  # noqa: E402
    CONTENT_GENERATION_PROCESSOR_FIELDS,
    CONTENT_GENERATION_PURPOSE,
)
from app.services.processor_credentials import ExternalProcessorService  # noqa: E402

MODEL_INFERENCE_PURPOSE = "model_inference"
MODEL_INFERENCE_FIELDS = {
    "instructions",
    "max_tokens",
    "temperature",
    "thinking",
    "user_payload",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register AssetGraph DeepSeek processor policies")
    parser.add_argument("--approved-by", default="workspace-owner")
    parser.add_argument("--region", default="cn")
    return parser


def _matches_policy(processor: dict[str, Any] | None, region: str) -> bool:
    if not processor or processor.get("status") != "active" or processor.get("region") != region:
        return False
    fields = (processor.get("minimum_fields") or {}).get(INTERACTION_PROCESSING_PURPOSE) or {}
    generation_fields = (processor.get("minimum_fields") or {}).get(CONTENT_GENERATION_PURPOSE) or {}
    inference_fields = (processor.get("minimum_fields") or {}).get(MODEL_INFERENCE_PURPOSE) or {}
    return bool(
        INTERACTION_PROCESSING_PURPOSE in set(processor.get("purposes") or [])
        and CONTENT_GENERATION_PURPOSE in set(processor.get("purposes") or [])
        and MODEL_INFERENCE_PURPOSE in set(processor.get("purposes") or [])
        and DataClassification.CONFIDENTIAL.value in set(processor.get("data_classes") or [])
        and INTERACTION_PROCESSOR_FIELDS.issubset(set(fields.get("allowed") or []))
        and CONTENT_GENERATION_PROCESSOR_FIELDS.issubset(set(generation_fields.get("allowed") or []))
        and MODEL_INFERENCE_FIELDS.issubset(set(inference_fields.get("allowed") or []))
    )


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / ".env", override=False)
    args = build_parser().parse_args(argv)
    if not args.region.strip():
        raise SystemExit("--region must not be empty")
    with connect(settings.postgres_dsn, row_factory=dict_row) as connection:
        repository = PrivacyGovernanceRepository(connection)
        current = repository.get_active_external_processor(settings.deepseek_processor_code)
        if _matches_policy(current, args.region):
            print(
                f"processor={settings.deepseek_processor_code} "
                f"revision={current['revision_number']} status=already-configured"
            )
            return 0
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT COALESCE(max(revision_number), 0)::integer + 1 AS revision
                FROM external_processor_records WHERE processor_code = %s
                """,
                (settings.deepseek_processor_code,),
            )
            revision = int(cursor.fetchone()["revision"])
        registered = ExternalProcessorService(repository).register(
            processor_code=settings.deepseek_processor_code,
            revision_number=revision,
            activate=True,
            purposes=sorted(
                {
                    *((current.get("purposes") or []) if current else []),
                    INTERACTION_PROCESSING_PURPOSE,
                    CONTENT_GENERATION_PURPOSE,
                    MODEL_INFERENCE_PURPOSE,
                }
            ),
            data_classes=[
                DataClassification(value)
                for value in sorted(
                    {
                        *((current.get("data_classes") or []) if current else []),
                        DataClassification.CONFIDENTIAL.value,
                    }
                )
            ],
            region=args.region,
            retention_terms=(
                "DeepSeek API processing under the configured account terms; "
                "AssetGraph transmits only approved interaction-analysis and content-generation fields"
            ),
            credential_owner="workspace-owner",
            rotation_policy="rotate the API key every 90 days and immediately after suspected exposure",
            minimum_fields={
                **(dict(current.get("minimum_fields") or {}) if current else {}),
                INTERACTION_PROCESSING_PURPOSE: {
                    "required": ["instructions", "temperature", "max_tokens", "thinking"],
                    "allowed": sorted(INTERACTION_PROCESSOR_FIELDS),
                },
                CONTENT_GENERATION_PURPOSE: {
                    "required": ["instructions", "temperature", "max_tokens", "thinking"],
                    "allowed": sorted(CONTENT_GENERATION_PROCESSOR_FIELDS),
                },
                MODEL_INFERENCE_PURPOSE: {
                    "required": ["instructions", "temperature", "max_tokens"],
                    "allowed": sorted(MODEL_INFERENCE_FIELDS),
                },
            },
            exit_plan=(
                "disable the processor record, clear the DeepSeek credential, "
                "and switch governed workloads to a local provider adapter"
            ),
            approved_by=args.approved_by,
        )
    print(
        f"processor={registered['processor_code']} "
        f"revision={registered['revision_number']} status={registered['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
