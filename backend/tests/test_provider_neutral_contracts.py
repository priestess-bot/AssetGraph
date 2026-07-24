from __future__ import annotations

from pathlib import Path

from pglast import parse_sql

from app.schemas.live_observations import AnalysisRunCreate, AnalysisRunRead
from app.schemas.maitu_workbench import WorkbenchPlanRevisionRead
from app.schemas.material_analysis import VideoAnalysisComplete
from app.services.live_observations import (
    default_aggregation_spec,
    default_chunk_analysis_specs,
)
from app.services.maitu_workbench import PIPELINE_SOURCE, PIPELINE_STAGE_ORDER


SUPPLIER_FIELDS = {
    "provider",
    "model_provider",
    "model_version",
    "requested_model",
    "actual_model",
    "generation_provider",
    "generation_requested_model",
    "generation_actual_model",
}


def test_provider_neutral_migration_parses_and_fences_new_producers() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "043_provider_neutral_producer_contracts.sql"
    )
    sql = migration.read_text(encoding="utf-8")

    parse_sql(sql)
    for field in (
        "generation_strategy_revision",
        "generation_invocation_evidence_ref",
        "strategy_revision",
        "invocation_evidence_ref",
        "analysis_strategy_revision",
        "analysis_prompt_revision",
    ):
        assert field in sql
    for constraint in (
        "chk_maitu_plan_provider_contract",
        "chk_maitu_plan_provider_evidence",
        "chk_live_analysis_provider_contract",
        "chk_live_analysis_provider_evidence",
        "chk_maitu_video_provider_contract",
        "chk_maitu_video_provider_evidence",
    ):
        assert constraint in sql
    assert "new producers must leave this null" in sql

    identity_migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "044_provider_neutral_analysis_identity.sql"
    )
    identity_sql = identity_migration.read_text(encoding="utf-8")
    parse_sql(identity_sql)
    assert "chk_maitu_video_neutral_analysis_identity" in identity_sql
    for field in (
        "analysis_prompt_revision IS NOT NULL",
        "analysis_input_fingerprint IS NOT NULL",
        "analysis_output_fingerprint IS NOT NULL",
    ):
        assert field in identity_sql


def test_business_request_and_response_models_expose_only_strategy_contracts() -> None:
    models = (
        AnalysisRunCreate,
        AnalysisRunRead,
        WorkbenchPlanRevisionRead,
        VideoAnalysisComplete,
    )
    for model in models:
        assert not (SUPPLIER_FIELDS & set(model.model_fields))

    assert "strategy_revision" in AnalysisRunCreate.model_fields
    assert "invocation_evidence_ref" in AnalysisRunRead.model_fields
    assert "generation_strategy_revision" in WorkbenchPlanRevisionRead.model_fields
    assert "analysis_strategy_revision" in VideoAnalysisComplete.model_fields


def test_automatic_analysis_dag_and_pipeline_identity_are_supplier_neutral() -> None:
    specs = [*default_chunk_analysis_specs(), default_aggregation_spec()]
    assert all("strategy_revision" in spec for spec in specs)
    assert all(not (SUPPLIER_FIELDS & set(spec)) for spec in specs)
    assert "deepseek" not in PIPELINE_SOURCE.lower()
    assert all("deepseek" not in stage.lower() for stage in PIPELINE_STAGE_ORDER)
