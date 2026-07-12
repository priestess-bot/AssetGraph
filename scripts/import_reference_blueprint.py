from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Any


def load_payload(*, payload_path: Path | None, profile_path: Path | None, blueprint_path: Path | None) -> dict[str, Any]:
    if payload_path is not None:
        return json.loads(payload_path.read_text(encoding="utf-8"))
    if profile_path is None or blueprint_path is None:
        raise ValueError("provide --payload, or provide both --profile and --blueprint")
    return {
        "reference_profile": json.loads(profile_path.read_text(encoding="utf-8")),
        "blueprint": json.loads(blueprint_path.read_text(encoding="utf-8")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import a Maitu reference-room blueprint through the AssetGraph API")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--blueprint", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = load_payload(
            payload_path=args.payload,
            profile_path=args.profile,
            blueprint_path=args.blueprint,
        )
    except ValueError as exc:
        parser.error(str(exc))
    request = urllib.request.Request(
        args.api_base_url.rstrip("/") + "/api/maitu/live-room-blueprints/import-reference",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        print(response.read().decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
