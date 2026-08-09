from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_ROOT = REPO_ROOT / "workers" / "browser-use"
PYTHON = Path(sys.executable).resolve()
BACKEND_ONLY_SECRET_KEYS = frozenset(
    {
        "ASSETGRAPH_MAITU_AUTHORITY_TOKEN",
        "MAITU_AUTHORITY_TOKEN",
        "ASSETGRAPH_MAITU_READBACK_ATTESTATION_KEY",
        "MAITU_READBACK_ATTESTATION_KEY",
        "DEEPSEEK_API_KEY",
        "ASSETGRAPH_DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "ASSETGRAPH_OPENAI_API_KEY",
    }
)


def run_cycle(*, download_missing: bool = False) -> int:
    environment = dict(os.environ)
    for key in BACKEND_ONLY_SECRET_KEYS:
        environment.pop(key, None)
    environment["PYTHONPATH"] = str(WORKER_ROOT / "src")
    inventory = [str(PYTHON), "-m", "browser_use_worker", "--sync-maitu-inventory"]
    if download_missing:
        inventory.append("--download-missing-maitu-materials")
    inventory_result = subprocess.run(inventory, cwd=WORKER_ROOT, env=environment, check=False)
    inspection_result = subprocess.run(
        [str(PYTHON), "-m", "browser_use_worker", "--run-room-inspection-job"],
        cwd=WORKER_ROOT,
        env=environment,
        check=False,
    )
    draft_result = subprocess.run(
        [str(PYTHON), "-m", "browser_use_worker", "--run-workbench-draft-job"],
        cwd=WORKER_ROOT,
        env=environment,
        check=False,
    )
    return max(inventory_result.returncode, inspection_result.returncode, draft_result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Maitu inventory and draft workbench queues")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--download-missing", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    args = parser.parse_args()
    if args.poll_seconds < 1:
        raise SystemExit("--poll-seconds must be at least 1")
    load_dotenv(REPO_ROOT / ".env", override=False)
    if args.once:
        return run_cycle(download_missing=args.download_missing)
    while True:
        run_cycle(download_missing=args.download_missing)
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
