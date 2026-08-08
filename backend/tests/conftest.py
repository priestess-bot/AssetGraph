from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.database_safety import (  # noqa: E402
    UnsafeTestDatabaseError,
    assert_test_database_is_isolated,
)


try:
    assert_test_database_is_isolated(
        os.getenv("ASSETGRAPH_TEST_DATABASE_URL"),
        development_env_file=REPO_ROOT / ".env",
    )
except UnsafeTestDatabaseError as exc:
    raise pytest.UsageError(str(exc)) from exc

TEST_ENV_FILE = REPO_ROOT / ".env.pytest-disabled"
os.environ["ASSETGRAPH_ENV_FILE"] = str(TEST_ENV_FILE)

WORKER_SRC = REPO_ROOT / "workers" / "browser-use" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))
