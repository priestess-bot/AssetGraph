from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.apply_migrations import database_url  # noqa: E402


GUIDED_WORKFLOW_VERSION = "guided-live.v1"


class ResetRefused(RuntimeError):
    """Raised when the requested reset is not sufficiently scoped or safe."""


@dataclass(frozen=True)
class ResetOptions:
    project_codes: tuple[str, ...]
    all_guided: bool
    confirm: bool
    database_url: str | None = None

    @property
    def dry_run(self) -> bool:
        return not self.confirm


@dataclass(frozen=True)
class TargetProject:
    project_id: UUID
    project_code: str
    current_revision_number: int


@dataclass(frozen=True)
class DomainReference:
    object_type: str
    object_code: str


@dataclass(frozen=True)
class RowCountSpec:
    table: str
    from_sql: str


@dataclass(frozen=True)
class DeleteStep:
    table: str
    delete_sql: str


SCOPE_CTE = """
WITH target_projects(id, project_code) AS (
    SELECT scope.id, scope.project_code
    FROM unnest(%s::uuid[], %s::text[]) AS scope(id, project_code)
)
"""


ROW_COUNT_SPECS: tuple[RowCountSpec, ...] = (
    RowCountSpec(
        "content_generation_job_items",
        """content_generation_job_items AS item
            JOIN content_generation_jobs AS job ON job.id = item.job_id
            JOIN target_projects AS target ON target.id = job.project_id""",
    ),
    RowCountSpec(
        "content_generation_jobs",
        "content_generation_jobs AS job JOIN target_projects AS target ON target.id = job.project_id",
    ),
    RowCountSpec(
        "content_guided_revision_archives",
        "content_guided_revision_archives AS archive JOIN target_projects AS target ON target.id = archive.project_id",
    ),
    RowCountSpec(
        "content_project_material_pool_revisions",
        "content_project_material_pool_revisions AS pool JOIN target_projects AS target ON target.id = pool.project_id",
    ),
    RowCountSpec(
        "functional_live_room_plan_release_snapshots",
        """functional_live_room_plan_release_snapshots AS snapshot
            JOIN functional_live_room_plans AS plan ON plan.id = snapshot.plan_id
            JOIN target_projects AS target ON target.project_code = plan.project_code""",
    ),
    RowCountSpec(
        "functional_live_room_operation_trace_links",
        """functional_live_room_operation_trace_links AS link
            JOIN functional_live_room_plans AS plan ON plan.id = link.plan_id
            JOIN target_projects AS target ON target.project_code = plan.project_code""",
    ),
    RowCountSpec(
        "maitu_workbench_draft_execution_jobs",
        """maitu_workbench_draft_execution_jobs AS job
            JOIN functional_live_room_plans AS plan ON plan.id = job.functional_plan_id
            JOIN target_projects AS target ON target.project_code = plan.project_code""",
    ),
    RowCountSpec(
        "functional_live_room_plans",
        "functional_live_room_plans AS plan JOIN target_projects AS target ON target.project_code = plan.project_code",
    ),
    RowCountSpec(
        "functional_video_plan_release_snapshots",
        """functional_video_plan_release_snapshots AS snapshot
            JOIN functional_video_plans AS plan ON plan.id = snapshot.plan_id
            JOIN target_projects AS target ON target.project_code = plan.project_code""",
    ),
    RowCountSpec(
        "functional_video_timeline_revisions",
        """functional_video_timeline_revisions AS revision
            JOIN functional_video_plans AS plan ON plan.id = revision.plan_id
            JOIN target_projects AS target ON target.project_code = plan.project_code""",
    ),
    RowCountSpec(
        "functional_video_timeline_segments",
        """functional_video_timeline_segments AS segment
            JOIN functional_video_plans AS plan ON plan.id = segment.plan_id
            JOIN target_projects AS target ON target.project_code = plan.project_code""",
    ),
    RowCountSpec(
        "functional_video_plans",
        "functional_video_plans AS plan JOIN target_projects AS target ON target.project_code = plan.project_code",
    ),
    RowCountSpec(
        "video_production_jobs",
        """video_production_jobs AS job
            JOIN production_variant_revisions AS revision ON revision.id = job.production_variant_revision_id
            JOIN production_variants AS variant ON variant.id = revision.variant_id
            JOIN target_projects AS target ON target.id = variant.project_id""",
    ),
    RowCountSpec(
        "maitu_workbench_runs",
        """maitu_workbench_runs AS run
            JOIN production_variant_revisions AS revision ON revision.id = run.production_variant_revision_id
            JOIN production_variants AS variant ON variant.id = revision.variant_id
            JOIN target_projects AS target ON target.id = variant.project_id""",
    ),
    RowCountSpec(
        "layer_blueprints",
        """layer_blueprints AS layer
            JOIN maitu_scene_blueprints AS scene ON scene.id = layer.scene_blueprint_id
            JOIN production_variant_revisions AS revision ON revision.id = scene.production_variant_revision_id
            JOIN production_variants AS variant ON variant.id = revision.variant_id
            JOIN target_projects AS target ON target.id = variant.project_id""",
    ),
    RowCountSpec(
        "maitu_scene_blueprints",
        """maitu_scene_blueprints AS scene
            JOIN production_variant_revisions AS revision ON revision.id = scene.production_variant_revision_id
            JOIN production_variants AS variant ON variant.id = revision.variant_id
            JOIN target_projects AS target ON target.id = variant.project_id""",
    ),
    RowCountSpec(
        "legacy_production_variant_links",
        """legacy_production_variant_links AS link
            JOIN production_variant_revisions AS revision ON revision.id = link.production_variant_revision_id
            JOIN production_variants AS variant ON variant.id = revision.variant_id
            JOIN target_projects AS target ON target.id = variant.project_id""",
    ),
    RowCountSpec(
        "live_room_configuration_revisions",
        """live_room_configuration_revisions AS revision
            JOIN live_room_configurations AS configuration ON configuration.id = revision.configuration_id
            JOIN production_variants AS variant ON variant.id = configuration.variant_id
            JOIN target_projects AS target ON target.id = variant.project_id""",
    ),
    RowCountSpec(
        "live_room_configurations",
        """live_room_configurations AS configuration
            JOIN production_variants AS variant ON variant.id = configuration.variant_id
            JOIN target_projects AS target ON target.id = variant.project_id""",
    ),
    RowCountSpec(
        "production_variant_revisions",
        """production_variant_revisions AS revision
            JOIN production_variants AS variant ON variant.id = revision.variant_id
            JOIN target_projects AS target ON target.id = variant.project_id""",
    ),
    RowCountSpec(
        "production_variants",
        "production_variants AS variant JOIN target_projects AS target ON target.id = variant.project_id",
    ),
    RowCountSpec(
        "shot_projection_links",
        """shot_projection_links AS link
            JOIN shots AS shot ON shot.id = link.shot_id
            JOIN shot_list_revisions AS revision ON revision.id = shot.shot_list_revision_id
            JOIN target_projects AS target ON target.id = revision.project_id""",
    ),
    RowCountSpec(
        "shot_script_block_sources",
        """shot_script_block_sources AS source
            JOIN shots AS shot ON shot.id = source.shot_id
            JOIN shot_list_revisions AS revision ON revision.id = shot.shot_list_revision_id
            JOIN target_projects AS target ON target.id = revision.project_id""",
    ),
    RowCountSpec(
        "shots",
        """shots AS shot
            JOIN shot_list_revisions AS revision ON revision.id = shot.shot_list_revision_id
            JOIN target_projects AS target ON target.id = revision.project_id""",
    ),
    RowCountSpec(
        "shot_list_revisions",
        "shot_list_revisions AS revision JOIN target_projects AS target ON target.id = revision.project_id",
    ),
    RowCountSpec(
        "program_segment_script_block_adoptions",
        """program_segment_script_block_adoptions AS adoption
            JOIN program_segments AS segment ON segment.id = adoption.segment_id
            JOIN content_program_revisions AS revision ON revision.id = segment.program_revision_id
            JOIN target_projects AS target ON target.id = revision.project_id""",
    ),
    RowCountSpec(
        "program_segments",
        """program_segments AS segment
            JOIN content_program_revisions AS revision ON revision.id = segment.program_revision_id
            JOIN target_projects AS target ON target.id = revision.project_id""",
    ),
    RowCountSpec(
        "content_program_revisions",
        "content_program_revisions AS revision JOIN target_projects AS target ON target.id = revision.project_id",
    ),
    RowCountSpec(
        "content_script_material_requirements",
        """content_script_material_requirements AS requirement
            JOIN content_script_revisions AS revision ON revision.id = requirement.script_revision_id
            JOIN target_projects AS target ON target.id = revision.project_id""",
    ),
    RowCountSpec(
        "content_script_blocks",
        """content_script_blocks AS block
            JOIN content_script_revisions AS revision ON revision.id = block.script_revision_id
            JOIN target_projects AS target ON target.id = revision.project_id""",
    ),
    RowCountSpec(
        "content_script_revisions",
        "content_script_revisions AS revision JOIN target_projects AS target ON target.id = revision.project_id",
    ),
    RowCountSpec(
        "story_brief_revisions",
        """story_brief_revisions AS revision
            JOIN story_briefs AS brief ON brief.id = revision.story_brief_id
            JOIN target_projects AS target ON target.id = brief.project_id""",
    ),
    RowCountSpec(
        "story_briefs",
        "story_briefs AS brief JOIN target_projects AS target ON target.id = brief.project_id",
    ),
    RowCountSpec(
        "functional_design_briefs",
        "functional_design_briefs AS brief JOIN target_projects AS target ON target.id = brief.project_id",
    ),
    RowCountSpec(
        "content_project_revisions",
        "content_project_revisions AS revision JOIN target_projects AS target ON target.id = revision.project_id",
    ),
    RowCountSpec(
        "content_projects",
        "content_projects AS project JOIN target_projects AS target ON target.id = project.id",
    ),
)


# Parent aggregates are deleted rather than immutable children where ON DELETE
# CASCADE owns the child cleanup. This keeps confirmed revision triggers intact.
DELETION_STEPS: tuple[DeleteStep, ...] = (
    DeleteStep(
        "maitu_workbench_draft_execution_jobs",
        """DELETE FROM maitu_workbench_draft_execution_jobs AS job
            USING functional_live_room_plans AS plan, target_projects AS target
            WHERE job.functional_plan_id = plan.id
              AND plan.project_code = target.project_code""",
    ),
    DeleteStep(
        "functional_live_room_plans",
        """DELETE FROM functional_live_room_plans AS plan
            USING target_projects AS target
            WHERE plan.project_code = target.project_code""",
    ),
    DeleteStep(
        "functional_video_plans",
        """DELETE FROM functional_video_plans AS plan
            USING target_projects AS target
            WHERE plan.project_code = target.project_code""",
    ),
    DeleteStep(
        "maitu_scene_blueprints",
        """DELETE FROM maitu_scene_blueprints AS scene
            WHERE scene.production_variant_revision_id IN (
                SELECT revision.id
                FROM production_variant_revisions AS revision
                JOIN production_variants AS variant ON variant.id = revision.variant_id
                JOIN target_projects AS target ON target.id = variant.project_id
            )""",
    ),
    DeleteStep(
        "legacy_production_variant_links",
        """DELETE FROM legacy_production_variant_links AS link
            WHERE link.production_variant_revision_id IN (
                SELECT revision.id
                FROM production_variant_revisions AS revision
                JOIN production_variants AS variant ON variant.id = revision.variant_id
                JOIN target_projects AS target ON target.id = variant.project_id
            )""",
    ),
    DeleteStep(
        "maitu_workbench_runs",
        """DELETE FROM maitu_workbench_runs AS run
            WHERE run.production_variant_revision_id IN (
                SELECT revision.id
                FROM production_variant_revisions AS revision
                JOIN production_variants AS variant ON variant.id = revision.variant_id
                JOIN target_projects AS target ON target.id = variant.project_id
            )""",
    ),
    DeleteStep(
        "video_production_jobs",
        """DELETE FROM video_production_jobs AS job
            WHERE job.production_variant_revision_id IN (
                SELECT revision.id
                FROM production_variant_revisions AS revision
                JOIN production_variants AS variant ON variant.id = revision.variant_id
                JOIN target_projects AS target ON target.id = variant.project_id
            )""",
    ),
    DeleteStep(
        "live_room_configurations",
        """DELETE FROM live_room_configurations AS configuration
            WHERE configuration.variant_id IN (
                SELECT variant.id
                FROM production_variants AS variant
                JOIN target_projects AS target ON target.id = variant.project_id
            )""",
    ),
    DeleteStep(
        "production_variants",
        """DELETE FROM production_variants AS variant
            USING target_projects AS target
            WHERE variant.project_id = target.id""",
    ),
    DeleteStep(
        "shot_list_revisions",
        """DELETE FROM shot_list_revisions AS revision
            USING target_projects AS target
            WHERE revision.project_id = target.id""",
    ),
    DeleteStep(
        "content_program_revisions",
        """DELETE FROM content_program_revisions AS revision
            USING target_projects AS target
            WHERE revision.project_id = target.id""",
    ),
    DeleteStep(
        "content_script_revisions",
        """DELETE FROM content_script_revisions AS revision
            USING target_projects AS target
            WHERE revision.project_id = target.id""",
    ),
    DeleteStep(
        "story_briefs",
        """DELETE FROM story_briefs AS brief
            USING target_projects AS target
            WHERE brief.project_id = target.id""",
    ),
    DeleteStep(
        "functional_design_briefs",
        """DELETE FROM functional_design_briefs AS brief
            USING target_projects AS target
            WHERE brief.project_id = target.id""",
    ),
    DeleteStep(
        "content_generation_jobs",
        """DELETE FROM content_generation_jobs AS job
            USING target_projects AS target
            WHERE job.project_id = target.id""",
    ),
    DeleteStep(
        "content_guided_revision_archives",
        """DELETE FROM content_guided_revision_archives AS archive
            USING target_projects AS target
            WHERE archive.project_id = target.id""",
    ),
    DeleteStep(
        "content_project_material_pool_revisions",
        """DELETE FROM content_project_material_pool_revisions AS pool
            USING target_projects AS target
            WHERE pool.project_id = target.id""",
    ),
    DeleteStep(
        "content_project_revisions",
        """DELETE FROM content_project_revisions AS revision
            USING target_projects AS target
            WHERE revision.project_id = target.id""",
    ),
    DeleteStep(
        "content_projects",
        """DELETE FROM content_projects AS project
            USING target_projects AS target
            WHERE project.id = target.id""",
    ),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Transactionally reset guided-live.v1 test projects. The default is a "
            "full deletion rehearsal followed by rollback."
        )
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--project-code",
        action="append",
        default=[],
        metavar="CODE",
        help="Project code to reset; repeat for multiple projects",
    )
    selection.add_argument(
        "--all-guided",
        action="store_true",
        help=(
            f"Preview every project whose current revision is {GUIDED_WORKFLOW_VERSION}; "
            "this inventory mode can never be committed"
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Commit the reset; without this flag every deletion is rolled back",
    )
    parser.add_argument(
        "--database-url",
        help=(
            "PostgreSQL DSN override; defaults to the same environment/.env resolution "
            "as scripts/apply_migrations.py"
        ),
    )
    return parser


def parse_options(argv: Sequence[str] | None = None) -> ResetOptions:
    parser = build_parser()
    args = parser.parse_args(argv)
    project_codes = tuple(
        dict.fromkeys(code.strip() for code in args.project_code if code.strip())
    )
    if args.project_code and len(project_codes) != len(args.project_code):
        parser.error("--project-code values must be non-empty and unique")
    if args.all_guided and args.confirm:
        parser.error(
            "--all-guided is dry-run only; commit requires explicit --project-code values"
        )
    return ResetOptions(
        project_codes=project_codes,
        all_guided=bool(args.all_guided),
        confirm=bool(args.confirm),
        database_url=args.database_url,
    )


def validate_runtime_guard(options: ResetOptions) -> None:
    if options.all_guided and options.project_codes:
        raise ResetRefused("--all-guided cannot be combined with explicit project codes")
    if not options.all_guided and not options.project_codes:
        raise ResetRefused("at least one project code is required unless --all-guided is used")
    if options.all_guided and options.confirm:
        raise ResetRefused(
            "--all-guided is dry-run only; commit requires explicit project codes"
        )


def resolve_targets(
    cursor: Any,
    *,
    project_codes: Sequence[str],
    all_guided: bool,
) -> list[TargetProject]:
    where_scope = ""
    params: list[Any] = [GUIDED_WORKFLOW_VERSION]
    if not all_guided:
        where_scope = "AND project.project_code = ANY(%s::text[])"
        params.append(list(project_codes))
    cursor.execute(
        f"""
        SELECT project.id AS project_id,
               project.project_code,
               project.current_revision_number
        FROM content_projects AS project
        JOIN content_project_revisions AS revision
          ON revision.project_id = project.id
         AND revision.revision_number = project.current_revision_number
        WHERE revision.content ->> 'workflow_version' = %s
          {where_scope}
        ORDER BY project.project_code
        FOR UPDATE OF project
        """,
        tuple(params),
    )
    rows = cursor.fetchall()
    targets = [
        TargetProject(
            project_id=UUID(str(row["project_id"])),
            project_code=str(row["project_code"]),
            current_revision_number=int(row["current_revision_number"]),
        )
        for row in rows
    ]
    if not targets:
        raise ResetRefused(
            f"no projects have a current {GUIDED_WORKFLOW_VERSION} revision in the requested scope"
        )
    if not all_guided:
        found = {target.project_code for target in targets}
        missing = [code for code in project_codes if code not in found]
        if missing:
            raise ResetRefused(
                "requested projects were not found or their current revision is not "
                f"{GUIDED_WORKFLOW_VERSION}: {', '.join(missing)}"
            )
    return targets


def _scope_parameters(targets: Sequence[TargetProject]) -> tuple[list[UUID], list[str]]:
    return (
        [target.project_id for target in targets],
        [target.project_code for target in targets],
    )


def collect_domain_references(
    cursor: Any, targets: Sequence[TargetProject]
) -> tuple[DomainReference, ...]:
    project_ids, project_codes = _scope_parameters(targets)
    references = {
        DomainReference(object_type, project_code)
        for project_code in project_codes
        for object_type in (
            "content_project",
            "content_project_revision",
            "content_script",
            "content_program",
            "shot_list",
        )
    }
    cursor.execute(
        f"""
        {SCOPE_CTE}
        SELECT 'story_brief' AS object_type, brief.story_brief_code AS object_code
        FROM story_briefs AS brief
        JOIN target_projects AS target ON target.id = brief.project_id
        UNION
        SELECT 'content_script', revision.script_revision_code
        FROM content_script_revisions AS revision
        JOIN target_projects AS target ON target.id = revision.project_id
        UNION
        SELECT 'content_program', revision.program_revision_code
        FROM content_program_revisions AS revision
        JOIN target_projects AS target ON target.id = revision.project_id
        UNION
        SELECT 'shot_list', revision.shot_list_revision_code
        FROM shot_list_revisions AS revision
        JOIN target_projects AS target ON target.id = revision.project_id
        UNION
        SELECT 'production_variant', variant.variant_code
        FROM production_variants AS variant
        JOIN target_projects AS target ON target.id = variant.project_id
        UNION
        SELECT 'live_room_configuration', configuration.configuration_code
        FROM live_room_configurations AS configuration
        JOIN production_variants AS variant ON variant.id = configuration.variant_id
        JOIN target_projects AS target ON target.id = variant.project_id
        UNION
        SELECT 'functional_live_room_plan', plan.plan_code
        FROM functional_live_room_plans AS plan
        JOIN target_projects AS target ON target.project_code = plan.project_code
        UNION
        SELECT 'functional_video_plan', plan.plan_code
        FROM functional_video_plans AS plan
        JOIN target_projects AS target ON target.project_code = plan.project_code
        """,
        (project_ids, project_codes),
    )
    for row in cursor.fetchall():
        references.add(
            DomainReference(str(row["object_type"]), str(row["object_code"]))
        )
    return tuple(sorted(references, key=lambda item: (item.object_type, item.object_code)))


def _row_count(row: Any, key: str) -> int:
    if isinstance(row, dict):
        return int(row[key])
    return int(row[0])


def collect_row_counts(
    cursor: Any,
    targets: Sequence[TargetProject],
    domain_references: Sequence[DomainReference],
) -> dict[str, int]:
    project_ids, project_codes = _scope_parameters(targets)
    counts: dict[str, int] = {}
    for spec in ROW_COUNT_SPECS:
        cursor.execute(
            f"{SCOPE_CTE} SELECT count(*) AS row_count FROM {spec.from_sql}",
            (project_ids, project_codes),
        )
        counts[spec.table] = _row_count(cursor.fetchone(), "row_count")

    reference_types = [reference.object_type for reference in domain_references]
    reference_codes = [reference.object_code for reference in domain_references]
    for table in ("stale_propagation_records", "domain_derivation_edges"):
        cursor.execute(
            f"""
            WITH domain_scope(object_type, object_code) AS (
                SELECT scope.object_type, scope.object_code
                FROM unnest(%s::text[], %s::text[]) AS scope(object_type, object_code)
            )
            SELECT count(*) AS row_count
            FROM {table} AS edge
            WHERE EXISTS (
                SELECT 1
                FROM domain_scope AS scope
                WHERE (edge.source_type = scope.object_type AND edge.source_code = scope.object_code)
                   OR (edge.target_type = scope.object_type AND edge.target_code = scope.object_code)
            )
            """,
            (reference_types, reference_codes),
        )
        counts[table] = _row_count(cursor.fetchone(), "row_count")
    return counts


def print_reset_plan(
    targets: Sequence[TargetProject],
    counts: dict[str, int],
    *,
    confirm: bool,
    output: Callable[[str], None],
) -> None:
    output(f"mode={'commit' if confirm else 'dry-run'}")
    output(f"workflow_version={GUIDED_WORKFLOW_VERSION}")
    output(f"target_projects={len(targets)}")
    output("target_project_codes:")
    for target in targets:
        output(f"  {target.project_code}")
    output("dependent_row_counts:")
    for table in sorted(counts):
        output(f"  {table}: {counts[table]}")
    output(f"  total: {sum(counts.values())}")


def _delete_polymorphic_rows(
    cursor: Any,
    table: str,
    domain_references: Sequence[DomainReference],
) -> int:
    reference_types = [reference.object_type for reference in domain_references]
    reference_codes = [reference.object_code for reference in domain_references]
    cursor.execute(
        f"""
        WITH domain_scope(object_type, object_code) AS (
            SELECT scope.object_type, scope.object_code
            FROM unnest(%s::text[], %s::text[]) AS scope(object_type, object_code)
        ), deleted AS (
            DELETE FROM {table} AS edge
            WHERE EXISTS (
                SELECT 1
                FROM domain_scope AS scope
                WHERE (edge.source_type = scope.object_type AND edge.source_code = scope.object_code)
                   OR (edge.target_type = scope.object_type AND edge.target_code = scope.object_code)
            )
            RETURNING 1
        )
        SELECT count(*) AS deleted_count FROM deleted
        """,
        (reference_types, reference_codes),
    )
    return _row_count(cursor.fetchone(), "deleted_count")


def delete_target_data(
    cursor: Any,
    targets: Sequence[TargetProject],
    domain_references: Sequence[DomainReference],
) -> dict[str, int]:
    deleted = {
        table: _delete_polymorphic_rows(cursor, table, domain_references)
        for table in ("stale_propagation_records", "domain_derivation_edges")
    }
    project_ids, project_codes = _scope_parameters(targets)
    for step in DELETION_STEPS:
        cursor.execute(
            f"""
            {SCOPE_CTE}, deleted AS (
                {step.delete_sql}
                RETURNING 1
            )
            SELECT count(*) AS deleted_count FROM deleted
            """,
            (project_ids, project_codes),
        )
        deleted[step.table] = _row_count(cursor.fetchone(), "deleted_count")
    return deleted


def verify_targets_deleted(cursor: Any, targets: Sequence[TargetProject]) -> None:
    project_ids, _ = _scope_parameters(targets)
    cursor.execute(
        "SELECT project_code FROM content_projects WHERE id = ANY(%s::uuid[]) ORDER BY project_code",
        (project_ids,),
    )
    remaining = cursor.fetchall()
    if remaining:
        codes = ", ".join(str(row["project_code"]) for row in remaining)
        raise RuntimeError(f"target projects still exist after reset: {codes}")


def run_reset(
    connection: Any,
    options: ResetOptions,
    *,
    output: Callable[[str], None] = print,
) -> list[TargetProject]:
    from psycopg.rows import dict_row

    try:
        validate_runtime_guard(options)
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT set_config('lock_timeout', '5000ms', true)")
            cursor.execute("SELECT set_config('statement_timeout', '300000ms', true)")
            targets = resolve_targets(
                cursor,
                project_codes=options.project_codes,
                all_guided=options.all_guided,
            )
            domain_references = collect_domain_references(cursor, targets)
            counts = collect_row_counts(cursor, targets, domain_references)
            print_reset_plan(targets, counts, confirm=options.confirm, output=output)
            delete_target_data(cursor, targets, domain_references)
            verify_targets_deleted(cursor, targets)
        if options.confirm:
            connection.commit()
            output(f"result=committed projects_deleted={len(targets)}")
        else:
            connection.rollback()
            output(f"result=dry-run-rolled-back projects_would_delete={len(targets)}")
        return targets
    except Exception:
        connection.rollback()
        raise


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_options(argv)
    import psycopg

    dsn = options.database_url or database_url(REPO_ROOT)
    try:
        connection = psycopg.connect(
            dsn,
            autocommit=False,
            application_name="assetgraph-guided-live-test-reset",
        )
    except Exception as exc:
        print(f"result=failed error={exc}", file=sys.stderr)
        return 1
    try:
        run_reset(connection, options)
    except ResetRefused as exc:
        print(f"result=refused transaction_rolled_back=true error={exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"result=failed transaction_rolled_back=true error={exc}", file=sys.stderr)
        return 1
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
