from __future__ import annotations

import argparse
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Protocol


ROOM_TEMPLATE_ROOT = "/api/live-research/room-templates"
REFERENCE_TEMPLATE_CONTRACT = "reference-blueprint-room-template.v1"


class ApiClient(Protocol):
    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any: ...


class AssetGraphApiClient:
    def __init__(self, api_base_url: str, *, timeout_seconds: float = 120.0) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.api_base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                content = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} {path}: {detail}") from exc
        if not content:
            return {}
        return json.loads(content.decode("utf-8"))


def load_payload(
    *,
    payload_path: Path | None,
    profile_path: Path | None,
    blueprint_path: Path | None,
) -> dict[str, Any]:
    if payload_path is not None:
        return json.loads(payload_path.read_text(encoding="utf-8"))
    if profile_path is None or blueprint_path is None:
        raise ValueError("provide --payload, or provide both --profile and --blueprint")
    return {
        "reference_profile": json.loads(profile_path.read_text(encoding="utf-8")),
        "blueprint": json.loads(blueprint_path.read_text(encoding="utf-8")),
    }


def canonical_json_checksum(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def reference_identity(payload: dict[str, Any]) -> tuple[str, str, str]:
    profile = payload.get("reference_profile")
    blueprint = payload.get("blueprint")
    if not isinstance(profile, dict) or not isinstance(blueprint, dict):
        raise ValueError("payload must contain reference_profile and blueprint objects")
    blueprint_code = str(blueprint.get("blueprint_code") or "").strip()
    room_id = str(
        blueprint.get("reference_room_id") or profile.get("reference_room_id") or ""
    ).strip()
    if not blueprint_code:
        raise ValueError("blueprint.blueprint_code is required for room-template materialization")
    if not room_id:
        raise ValueError("reference_room_id is required for room-template materialization")
    return blueprint_code, room_id, canonical_json_checksum(blueprint)


def identity_marker(blueprint_code: str, room_id: str) -> str:
    code = urllib.parse.quote(blueprint_code, safe="")
    room = urllib.parse.quote(room_id, safe="")
    return f"assetgraph-reference-blueprint://{code}/{room}"


def provenance_for(
    *,
    blueprint_code: str,
    room_id: str,
    source_checksum: str,
) -> dict[str, Any]:
    return {
        "source_contract": REFERENCE_TEMPLATE_CONTRACT,
        "reference_blueprint_code": blueprint_code,
        "reference_room_id": room_id,
        "source_checksum_sha256": source_checksum,
        "checksum_scope": "canonical_blueprint_json",
        "layout_fidelity": "approximate",
        "buildability": "reference_only",
    }


def _template_description(blueprint_code: str, room_id: str) -> str:
    return (
        f"Layout hypothesis materialized from reference blueprint {blueprint_code} "
        f"for room {room_id}; layout_fidelity=approximate; "
        f"buildability=reference_only; not an executable room layout.\n"
        f"{identity_marker(blueprint_code, room_id)}"
    )


def _request_object(
    client: ApiClient,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = client.request_json(method, path, payload)
    if not isinstance(value, dict):
        raise RuntimeError(f"{method} {path} did not return an object")
    return value


def _all_room_template_summaries(client: ApiClient) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    limit = 100
    while True:
        query = urllib.parse.urlencode({"limit": limit, "offset": offset})
        value = client.request_json("GET", f"{ROOM_TEMPLATE_ROOT}?{query}")
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise RuntimeError("GET room-templates did not return an object list")
        batch = list(value)
        rows.extend(batch)
        if len(batch) < limit:
            return rows
        offset += limit


def _template_matches_identity(
    template: dict[str, Any],
    *,
    blueprint_code: str,
    room_id: str,
) -> bool:
    marker = identity_marker(blueprint_code, room_id)
    if marker in str(template.get("description") or ""):
        return True
    for revision in template.get("revisions") or []:
        if not isinstance(revision, dict):
            continue
        provenance = revision.get("provenance")
        if not isinstance(provenance, dict):
            continue
        if (
            str(provenance.get("reference_blueprint_code") or "") == blueprint_code
            and str(provenance.get("reference_room_id") or "") == room_id
        ):
            return True
    return False


def find_unique_room_template(
    client: ApiClient,
    *,
    blueprint_code: str,
    room_id: str,
) -> dict[str, Any] | None:
    matches: dict[str, dict[str, Any]] = {}
    for summary in _all_room_template_summaries(client):
        template_code = str(summary.get("template_code") or "").strip()
        if not template_code:
            raise RuntimeError("room-template summary is missing template_code")
        detail = _request_object(
            client,
            "GET",
            f"{ROOM_TEMPLATE_ROOT}/{urllib.parse.quote(template_code, safe='')}",
        )
        if _template_matches_identity(
            detail,
            blueprint_code=blueprint_code,
            room_id=room_id,
        ):
            matches[template_code] = detail
    if len(matches) > 1:
        codes = ", ".join(sorted(matches))
        raise RuntimeError(
            "multiple room templates match reference blueprint "
            f"{blueprint_code} / room {room_id}: {codes}"
        )
    if not matches:
        return None
    template = next(iter(matches.values()))
    if template.get("template_kind") != "layout_hypothesis":
        raise RuntimeError("matching room template is not a layout_hypothesis")
    if template.get("status") == "archived" or template.get("archived_at"):
        raise RuntimeError("matching room template is archived and cannot be restored via API")
    return template


def _duration_seconds(scene: dict[str, Any]) -> float:
    try:
        duration = float(scene.get("estimated_duration_seconds") or 30)
    except (TypeError, ValueError):
        duration = 30.0
    return duration if duration > 0 else 30.0


def _unique_component_id(base: str, used: set[str]) -> str:
    candidate = base[:128] or "component"
    suffix = 2
    while candidate in used:
        tail = f"-{suffix}"
        candidate = f"{base[: 128 - len(tail)]}{tail}"
        suffix += 1
    used.add(candidate)
    return candidate


def build_revision_payload(payload: dict[str, Any]) -> dict[str, Any]:
    blueprint_code, room_id, source_checksum = reference_identity(payload)
    blueprint = payload["blueprint"]
    raw_scenes = blueprint.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("blueprint.scenes must contain at least one scene")

    script_by_scene = {
        str(item.get("scene_name")): str(item.get("content") or "")
        for item in blueprint.get("script_blocks") or []
        if isinstance(item, dict) and item.get("scene_name")
    }
    scenes: list[dict[str, Any]] = []
    components: list[dict[str, Any]] = []
    used_component_ids: set[str] = set()
    start_seconds = 0.0

    for scene_index, raw_scene in enumerate(raw_scenes):
        if not isinstance(raw_scene, dict):
            raise ValueError("blueprint.scenes entries must be objects")
        scene_key = str(
            raw_scene.get("scene_code") or f"{blueprint_code}-scene-{scene_index + 1:03d}"
        )[:128]
        scene_name = str(raw_scene.get("scene_name") or scene_key)
        duration = _duration_seconds(raw_scene)
        end_seconds = start_seconds + duration
        layers = [item for item in raw_scene.get("layers") or [] if isinstance(item, dict)]
        material_slots = [
            {
                "slot_key": str(layer.get("layer_code") or f"slot-{index + 1}"),
                "role": str(layer.get("layer_role") or "unknown"),
                "required_category": layer.get("required_category"),
                "accepted_asset_types": list(layer.get("accepted_asset_types") or []),
                "replacement_policy": layer.get("replacement_policy"),
            }
            for index, layer in enumerate(layers)
        ]
        scenes.append(
            {
                "scene_key": scene_key,
                "name": scene_name,
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "purpose": raw_scene.get("goal"),
                "script_pattern": script_by_scene.get(scene_name),
                "material_slots": material_slots,
                "reference_scene_code": raw_scene.get("scene_code"),
                "reference_active": bool(raw_scene.get("reference_active", False)),
            }
        )
        for layer_index, layer in enumerate(layers):
            base_id = str(
                layer.get("layer_code") or f"{scene_key}-component-{layer_index + 1:03d}"
            )
            component_id = _unique_component_id(base_id, used_component_ids)
            components.append(
                {
                    "component_id": component_id,
                    "scene_key": scene_key,
                    "role": str(
                        layer.get("layer_role") or layer.get("required_category") or "unknown"
                    )[:64],
                    "start_seconds": start_seconds,
                    "end_seconds": end_seconds,
                    "z_index": layer.get("sort_order"),
                    "observability": "observed",
                    "source_binding_status": "unmatched",
                    "audio_classification": "unknown",
                    "muted": True,
                    "confidence": 0.6,
                    "evidence": [
                        {
                            "source": "reference_blueprint",
                            "reference_blueprint_code": blueprint_code,
                            "reference_room_id": room_id,
                            "source_checksum_sha256": source_checksum,
                            "reference_layer_code": layer.get("layer_code"),
                            "reference_layer_name": layer.get("layer_name"),
                        }
                    ],
                    "ambiguities": [
                        "Reference observation does not prove executable geometry or source binding"
                    ],
                }
            )
        start_seconds = end_seconds

    provenance = provenance_for(
        blueprint_code=blueprint_code,
        room_id=room_id,
        source_checksum=source_checksum,
    )
    return {
        "contract_version": "layout-hypothesis.v1",
        "canvas": {
            "width": 1080,
            "height": 1920,
            "rotation_degrees": 0,
            "pixel_aspect_ratio": "1:1",
        },
        "scenes": scenes,
        "components": components,
        "audio_policy": {
            "max_active_speech": 1,
            "max_active_bgm": 1,
            "unknown_audio_default_muted": True,
            "allow_overlapping_bgm_crossfade": False,
            "speech_ducking_db": -9,
        },
        "provenance": provenance,
        "content_readiness": "review_required",
        "layout_fidelity": "approximate",
        "buildability": "reference_only",
        "layout_reference": {
            "reference_blueprint_code": blueprint_code,
            "reference_room_id": room_id,
            "source_checksum_sha256": source_checksum,
            "approximate": True,
            "reference_only": True,
        },
        "confidence": 0.6,
        "created_by": "import_reference_blueprint.py",
    }


def _latest_revision(template: dict[str, Any]) -> dict[str, Any] | None:
    revisions = [item for item in template.get("revisions") or [] if isinstance(item, dict)]
    if not revisions:
        return None
    return max(revisions, key=lambda item: int(item.get("revision_number") or 0))


def _revision_has_source(
    revision: dict[str, Any],
    *,
    blueprint_code: str,
    room_id: str,
    source_checksum: str,
) -> bool:
    provenance = revision.get("provenance")
    return isinstance(provenance, dict) and provenance == provenance_for(
        blueprint_code=blueprint_code,
        room_id=room_id,
        source_checksum=source_checksum,
    )


def materialize_room_template(
    payload: dict[str, Any],
    *,
    client: ApiClient,
    publish: bool,
    template_name: str | None = None,
) -> dict[str, Any]:
    blueprint_code, room_id, source_checksum = reference_identity(payload)
    template = find_unique_room_template(
        client,
        blueprint_code=blueprint_code,
        room_id=room_id,
    )
    if template is None:
        name = template_name or f"Room {room_id} reference layout baseline"
        template = _request_object(
            client,
            "POST",
            ROOM_TEMPLATE_ROOT,
            {
                "name": name,
                "description": _template_description(blueprint_code, room_id),
                "template_kind": "layout_hypothesis",
            },
        )
        template_action = "created"
        created_template_code = str(template.get("template_code") or "").strip()
        template = find_unique_room_template(
            client,
            blueprint_code=blueprint_code,
            room_id=room_id,
        )
        if template is None or template.get("template_code") != created_template_code:
            raise RuntimeError("created room template could not be recovered uniquely")
    else:
        template_action = "reused"

    template_code = str(template.get("template_code") or "").strip()
    if not template_code:
        raise RuntimeError("room-template response is missing template_code")
    if template.get("template_kind") != "layout_hypothesis":
        raise RuntimeError("room-template response is not a layout_hypothesis")

    latest = _latest_revision(template)
    reusable_statuses = {"draft", "published"}
    if publish:
        reusable_statuses.add("rejected")
    if (
        latest is not None
        and latest.get("status") in reusable_statuses
        and _revision_has_source(
            latest,
            blueprint_code=blueprint_code,
            room_id=room_id,
            source_checksum=source_checksum,
        )
    ):
        revision = latest
        revision_action = "reused"
    else:
        revision = _request_object(
            client,
            "POST",
            f"{ROOM_TEMPLATE_ROOT}/{urllib.parse.quote(template_code, safe='')}/revisions",
            build_revision_payload(payload),
        )
        revision_action = "created"

    revision_number = int(revision.get("revision_number") or 0)
    if revision_number < 1:
        raise RuntimeError("room-template revision response is missing revision_number")
    if publish and revision.get("status") != "published":
        _request_object(
            client,
            "POST",
            (
                f"{ROOM_TEMPLATE_ROOT}/{urllib.parse.quote(template_code, safe='')}"
                f"/revisions/{revision_number}/publish"
            ),
            {
                "reviewed_by": "reference_blueprint_importer",
                "review_notes": (
                    "Published only as an approximate, reference_only layout hypothesis; "
                    "no executable geometry or source binding is asserted."
                ),
                "published_by": "reference_blueprint_importer",
                "publication_reason": (
                    f"Materialize reference blueprint {blueprint_code} for room {room_id}"
                ),
            },
        )
        publication_action = "published"
    elif publish:
        publication_action = "reused"
    else:
        publication_action = "not_requested"

    final_template = _request_object(
        client,
        "GET",
        f"{ROOM_TEMPLATE_ROOT}/{urllib.parse.quote(template_code, safe='')}",
    )
    return {
        "template_code": template_code,
        "template_action": template_action,
        "revision_number": revision_number,
        "revision_action": revision_action,
        "publication_action": publication_action,
        "status": final_template.get("status"),
        "published_revision_number": final_template.get("published_revision_number"),
        "reference_blueprint_code": blueprint_code,
        "reference_room_id": room_id,
        "source_checksum_sha256": source_checksum,
        "layout_fidelity": "approximate",
        "buildability": "reference_only",
    }


def run_import(
    payload: dict[str, Any],
    *,
    client: ApiClient,
    materialize: bool = False,
    publish: bool = False,
    template_name: str | None = None,
) -> dict[str, Any]:
    imported = _request_object(
        client,
        "POST",
        "/api/maitu/live-room-blueprints/import-reference",
        payload,
    )
    if not materialize and not publish:
        return imported
    return {
        "blueprint": imported,
        "room_template": materialize_room_template(
            payload,
            client=client,
            publish=publish,
            template_name=template_name,
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import a Maitu reference-room blueprint through the AssetGraph API"
    )
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--blueprint", type=Path)
    parser.add_argument(
        "--materialize-room-template",
        action="store_true",
        help="Create or reuse one formal layout_hypothesis room template",
    )
    parser.add_argument(
        "--publish-room-template",
        action="store_true",
        help="Publish the matching revision after materialization",
    )
    parser.add_argument(
        "--room-template-name",
        help="Name used only when a new formal room template must be created",
    )
    args = parser.parse_args(argv)
    try:
        payload = load_payload(
            payload_path=args.payload,
            profile_path=args.profile,
            blueprint_path=args.blueprint,
        )
    except ValueError as exc:
        parser.error(str(exc))
    client = AssetGraphApiClient(args.api_base_url)
    result = run_import(
        payload,
        client=client,
        materialize=args.materialize_room_template,
        publish=args.publish_room_template,
        template_name=args.room_template_name,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
