#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from pathlib import Path

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from psycopg import Connection, connect  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.content_workflow import GuidedContentGenerationWorker  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run durable guided content-generation jobs")
    parser.add_argument(
        "--worker-id", default=f"guided-content-{socket.gethostname()}-{os.getpid()}"
    )
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--error-backoff-seconds", type=float, default=5.0)
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / ".env", override=False)
    args = build_parser().parse_args(argv)
    if args.poll_seconds < 0.1:
        raise SystemExit("--poll-seconds must be at least 0.1")
    if args.error_backoff_seconds < 1:
        raise SystemExit("--error-backoff-seconds must be at least 1")
    connection: Connection | None = None
    while True:
        try:
            if connection is None or connection.closed:
                connection = connect(settings.postgres_dsn, row_factory=dict_row)
            worker = GuidedContentGenerationWorker(connection)
            job = worker.run_once(args.worker_id)
            if job is not None:
                print(
                    f"job={job['job_code']} stage={job['stage']} status={job['status']} "
                    f"progress={job['completed_items']}/{job['total_items']}",
                    flush=True,
                )
            if args.once:
                return 0
            if job is None:
                time.sleep(args.poll_seconds)
            elif job["status"] == "queued":
                time.sleep(min(30.0, max(args.poll_seconds, 2 ** int(job["attempts"]))))
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            if connection is not None:
                connection.close()
                connection = None
            if args.once:
                raise
            print(
                f"worker_error={exc.__class__.__name__} message={exc}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(args.error_backoff_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
