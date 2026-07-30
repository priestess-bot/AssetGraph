# Customer Experience v1 Test Matrix

Date: 2026-07-26

## Release Gate Result

| Surface | Command | Result |
| --- | --- | --- |
| Backend unit, contract and PostgreSQL integration | `ASSETGRAPH_TEST_DATABASE_URL=... uv run pytest -q --tb=short` | 904 passed, 0 failed, 0 skipped |
| Frontend unit and interaction | `npm test -- --run --maxWorkers=1` | 23 files, 142 passed |
| Frontend type contract | `npm run typecheck` | passed |
| Console, Maitu and live-research production bundles | `npm run build` | all three bundles built |
| Browser-use worker | `uv run pytest -q --tb=short` | 388 passed |
| Live-research worker | `uv run pytest -q --tb=short` | 30 passed |
| Local Kokoro TTS HTTP contract | `uv run pytest -q --tb=short` | 4 passed |
| Backend lint | `uv run ruff check .` | passed |
| Browser-use worker lint | `uv run ruff check .` | passed |
| Live-research worker lint | `uv run ruff check .` | passed |

The PostgreSQL run used a new database created from all 103 ordered migrations. No
environment-dependent tests were skipped in the release-gate run.

## Defects Closed During The Gate

- Restriction text such as "do not promise a price" no longer becomes an
  uncited affirmative price claim.
- Historical `contain` timeline clips no longer restore with an invalid crop
  focus, and new timelines only persist crop focus for `cover` clips.
- Functional video responses now expose the frozen material and constraint
  snapshots used by the production variant.
- Video release snapshots allocate artifact codes from the shared artifact
  sequence, preventing cross-carrier code collisions.
- Repository tests can claim their exact video job without consuming another
  queued production job.
- Asset-group deep links survive refresh and keep selected members first for
  review without changing membership semantics.
- The Maitu login probe no longer treats the transient SPA shell as an
  authenticated page before it redirects to `/Login`.
- Customer-facing status copy no longer presents optional platform capture or
  unverified Maitu reads and mutations as currently available capabilities.

## Non-Blocking Build Observation

The Console JavaScript bundle is 933.85 kB before gzip and emits Vite's 500 kB
chunk warning. It builds and loads successfully, but route-level code splitting
is retained as a post-v1 performance item.
