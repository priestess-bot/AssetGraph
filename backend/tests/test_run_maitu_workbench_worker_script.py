from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_maitu_workbench_worker.py"


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "assetgraph_run_maitu_workbench_worker",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_reuses_the_active_python_interpreter() -> None:
    module = _load_script()

    assert module.PYTHON == Path(sys.executable).resolve()
