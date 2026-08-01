#!/usr/bin/env python3
"""Probe, classify, constrain, and evidence-bind the curated local materials."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

import psycopg


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import settings  # noqa: E402
from app.services.material_bootstrap import (  # noqa: E402
    apply_bootstrap_plan,
    build_bootstrap_plan,
    build_report,
    list_database_material_assets,
    load_catalog,
    load_inventory_observation,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap the 63 curated local materials.")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("/DATA/Downloads/AssetGraph/catalog/current_asset_inventory.json"),
    )
    parser.add_argument(
        "--inventory-observation",
        type=Path,
        default=Path(
            "/DATA/Downloads/AssetGraph/maitu-mirror/inventory-observations/"
            "f1d8a08584015403e6ae8218eeb9f989322d6c19b0a37c8cbc45763fff4cefd9.json"
        ),
    )
    parser.add_argument("--assets-root", type=Path, default=settings.asset_materials_root)
    parser.add_argument("--expected-count", type=int, default=63)
    parser.add_argument("--apply", action="store_true", help="Persist the reviewed plan; default is dry-run.")
    parser.add_argument("--report-output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    with psycopg.connect(settings.postgres_dsn) as connection:
        plan = build_bootstrap_plan(
            catalog_assets=load_catalog(args.catalog),
            database_assets=list_database_material_assets(connection),
            observation=load_inventory_observation(args.inventory_observation),
            observation_path=args.inventory_observation,
            assets_root=args.assets_root,
            expected_count=args.expected_count,
        )
        report = apply_bootstrap_plan(connection, plan) if args.apply else build_report(plan, mode="dry_run")
    if args.report_output:
        args.report_output.parent.mkdir(parents=True, exist_ok=True)
        args.report_output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({key: value for key, value in report.items() if key != "items"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
