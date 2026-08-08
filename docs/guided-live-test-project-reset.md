# Guided-live test project reset

`scripts/reset_guided_live_test_projects.py` is a one-time maintenance utility for removing known test projects created by the `guided-live.v1` workflow. It cannot infer whether a project is test data. The operator must first verify every explicit project code. The utility selects a project only when its **current** `content_project_revision` has `content.workflow_version == "guided-live.v1"`. A project with only an older guided revision is refused.

The utility is deliberately conservative:

- Dry-run is the default. It executes the complete deletion plan in one transaction and then rolls the transaction back, so foreign-key problems are found before a committed run.
- One or more explicit `--project-code` values are required unless `--all-guided` is used.
- `--confirm` is required to commit.
- `--all-guided` is inventory-only and can never be committed. Every committed run must name each project code explicitly.
- Target project codes and row counts are printed before any delete statement runs.
- Any selection, SQL, foreign-key, or commit failure rolls back the transaction.
- Assets, asset groups, knowledge records, fact records, content rules, and live-room templates are never deletion targets. References from project rows are removed while those shared resources remain intact.

## Database configuration

Database settings use the same resolution as `scripts/apply_migrations.py`. Prefer `ASSETGRAPH_DATABASE_URL`; `DATABASE_URL`, `ASSETGRAPH_ENV_FILE`, the repository `.env`, and the existing `POSTGRES_*` settings are also supported. The script contains no credentials and never prints the resolved DSN.

Run it with the backend virtual environment or another Python environment containing the backend dependencies.

## Commands

Preview one project. This runs the deletion rehearsal and rolls it back:

```powershell
backend\.venv\Scripts\python.exe scripts\reset_guided_live_test_projects.py `
  --project-code CONTENT-TEST-000001
```

Preview several explicit projects:

```powershell
backend\.venv\Scripts\python.exe scripts\reset_guided_live_test_projects.py `
  --project-code CONTENT-TEST-000001 `
  --project-code CONTENT-TEST-000002
```

Commit an explicit reset only after reviewing the dry-run output:

```powershell
backend\.venv\Scripts\python.exe scripts\reset_guided_live_test_projects.py `
  --project-code CONTENT-TEST-000001 `
  --confirm
```

Preview every currently eligible guided project:

```powershell
backend\.venv\Scripts\python.exe scripts\reset_guided_live_test_projects.py --all-guided
```

The all-project form is a read-only inventory rehearsal. `--all-guided --confirm` is always refused; copy only verified test project codes into a separate explicit command.

On Linux, use the equivalent interpreter, for example `.venv/bin/python`.

## Deleted data

The transaction removes project-owned guided generation jobs and job items, revision archives, material-pool revisions, functional live-room plans selected by `project_code` and their dependent rows, functional video plans if present, production projections if present, shot lists, programs, scripts, story briefs, project revisions, and the project itself. Parent aggregates are deleted in foreign-key-safe order so their immutable child rows can cascade normally.

Polymorphic `domain_derivation_edges` and `stale_propagation_records` are removed when either endpoint matches a typed code collected from the target project and its derived content. Unknown cross-project references are not modified; if they prevent deletion, the complete transaction fails and rolls back.

The output ends with one of these transaction outcomes:

- `result=dry-run-rolled-back`: no reset data was committed.
- `result=committed`: the selected projects were deleted.
- `result=refused` or `result=failed`: the transaction was rolled back.

Take a database backup before the committed run. The utility intentionally has no restore operation.
