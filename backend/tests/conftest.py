from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_ENV_FILE = REPO_ROOT / ".env.pytest-disabled"
os.environ["ASSETGRAPH_ENV_FILE"] = str(TEST_ENV_FILE)

WORKER_SRC = REPO_ROOT / "workers" / "browser-use" / "src"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))
