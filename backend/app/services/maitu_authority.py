from __future__ import annotations

import hashlib
import hmac
import json
import math
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

import httpx

from app.core.config import settings


class MaituAuthorityError(RuntimeError):
    """The backend could not independently verify a Maitu readback."""


class MaituAuthorityConfigurationError(MaituAuthorityError):
    """Backend-only authority credentials or transport configuration are invalid."""


class MaituAuthorityUpstreamError(MaituAuthorityError):
    """The authoritative Maitu API is temporarily unavailable or malformed."""


def get_maitu_authority_verifier() -> Iterator["MaituAuthorityVerifier"]:
    verifier = MaituAuthorityVerifier()
    try:
        yield verifier
    finally:
        verifier.close()


class MaituAuthorityVerifier:
    """Backend-only Maitu verifier; the mutation Worker never receives these credentials."""

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        token = settings.maitu_authority_token
        signing_key = settings.maitu_readback_attestation_key
        self._token = token.get_secret_value() if token is not None else ""
        self._signing_key = signing_key.get_secret_value() if signing_key is not None else ""
        base_url = str(settings.maitu_authority_base_url).rstrip("/")
        timeout = float(settings.maitu_authority_timeout_seconds)
        if base_url != "https://api.maituai.com":
            raise MaituAuthorityConfigurationError("backend Maitu authority origin is not trusted")
        if not math.isfinite(timeout) or timeout <= 0:
            raise MaituAuthorityConfigurationError("backend Maitu authority timeout is invalid")
        self._client = client or httpx.Client(
            base_url=base_url + "/",
            headers={"Authorization": self._token},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _unwrap(value: Any) -> Any:
        if isinstance(value, dict) and value.get("success") is True and "data" in value:
            return value["data"]
        return value

    def _get(self, path: str) -> Any:
        if len(self._token) < 16:
            raise MaituAuthorityConfigurationError("backend Maitu authority token is not configured")
        try:
            response = self._client.get(path)
            response.raise_for_status()
            return self._unwrap(response.json())
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {401, 403}:
                raise MaituAuthorityConfigurationError("backend Maitu authority authentication failed") from exc
            if status_code == 429 or status_code >= 500:
                raise MaituAuthorityUpstreamError("backend Maitu authority is temporarily unavailable") from exc
            raise MaituAuthorityError(f"backend Maitu authority rejected readback for {path}") from exc
        except (httpx.RequestError, ValueError) as exc:
            raise MaituAuthorityUpstreamError(f"backend Maitu authority readback failed for {path}") from exc

    @staticmethod
    def _canonical(value: Any) -> bytes:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _sign(self, value: dict[str, Any]) -> str:
        if len(self._signing_key) < 32:
            raise MaituAuthorityConfigurationError("backend Maitu readback signing key is not configured")
        return hmac.new(self._signing_key.encode("utf-8"), self._canonical(value), hashlib.sha256).hexdigest()

    @staticmethod
    def _same_id(actual: Any, expected: Any) -> bool:
        return actual is not None and expected is not None and str(actual) == str(expected)

    @staticmethod
    def _number(value: Any) -> float | None:
        if value is None or isinstance(value, bool) or value == "":
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _public_inventory_url(value: Any, *, required: bool) -> str | None:
        if value is None or value == "":
            if required:
                raise MaituAuthorityError("backend Maitu inventory material URL is missing")
            return None
        if not isinstance(value, str):
            raise MaituAuthorityError("backend Maitu inventory material URL is invalid")
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise MaituAuthorityError("backend Maitu inventory material URL is not trusted HTTPS")
        allowed_query_keys = {"x-oss-process"}
        if any(key.lower() not in allowed_query_keys for key, _item in parse_qsl(parsed.query, keep_blank_values=True)):
            raise MaituAuthorityError("backend Maitu inventory material URL contains credential-like query data")
        return value

    @staticmethod
    def _clips(room: dict[str, Any]) -> list[dict[str, Any]]:
        topics = room.get("topics") if isinstance(room, dict) else None
        topic = topics[0] if isinstance(topics, list) and topics and isinstance(topics[0], dict) else {}
        clips = topic.get("clips")
        return [item for item in clips if isinstance(item, dict)] if isinstance(clips, list) else []

    @staticmethod
    def _materials(clip: dict[str, Any]) -> list[dict[str, Any]]:
        materials = clip.get("clip_materials")
        return [item for item in materials if isinstance(item, dict)] if isinstance(materials, list) else []

    @classmethod
    def _material_style(cls, material: dict[str, Any]) -> dict[str, Any]:
        raw = material.get("style_front")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                return {}
        if isinstance(raw, dict):
            return raw
        raw = material.get("style")
        return raw if isinstance(raw, dict) else material

    @classmethod
    def _material_source_matches(cls, material: dict[str, Any], intent: dict[str, Any]) -> bool:
        expected_type = intent.get("source_material_type")
        if expected_type == "decorative_video":
            expected_type = "video"
        if material.get("type") != expected_type:
            return False
        if expected_type == "digital_human":
            return cls._same_id(material.get("speaker_id"), intent.get("speaker_id")) and cls._same_id(
                material.get("digital_human_image_id"), intent.get("digital_human_image_id")
            )
        expected_material_id = intent.get("material_id") or intent.get("maitu_material_id") or intent.get(
            "source_material_id"
        )
        return cls._same_id(material.get("material_id"), expected_material_id) and str(material.get("url") or "") == str(
            intent.get("source_material_url") or ""
        )

    @classmethod
    def _material_geometry_matches(cls, material: dict[str, Any], intent: dict[str, Any]) -> bool:
        style = cls._material_style(material)
        return all(
            cls._number(style.get(actual_key)) is not None
            and cls._number(style.get(actual_key)) == cls._number(intent.get(intent_key))
            for actual_key, intent_key in (
                ("left", "left"),
                ("top", "top"),
                ("width", "width"),
                ("height", "height"),
                ("zIndex", "z_index"),
            )
        )

    @staticmethod
    def _scene_candidates(clips: list[dict[str, Any]], intent: dict[str, Any]) -> list[dict[str, Any]]:
        scene_name = intent.get("scene_name")
        if not isinstance(scene_name, str) or not scene_name:
            raise MaituAuthorityError("operation intent has no target scene name")
        return [clip for clip in clips if clip.get("name") == scene_name]

    @classmethod
    def _find_by_id(cls, rows: list[dict[str, Any]], identity: Any) -> dict[str, Any] | None:
        return next((row for row in rows if cls._same_id(row.get("id"), identity)), None)

    def _read_working_room(self, live_room_id: str) -> dict[str, Any]:
        room = self._get(f"live_rooms/{live_room_id}?env=working&include_qa_clips=true")
        if not isinstance(room, dict):
            raise MaituAuthorityError("authoritative Maitu working-room response is not an object")
        if not self._same_id(room.get("id"), live_room_id):
            raise MaituAuthorityError("authoritative Maitu working-room identity mismatch")
        explicit_environment = room.get("environment") in {"working", "draft"} or room.get("env") in {
            "working",
            "draft",
        }
        if not explicit_environment and not isinstance(room.get("topics"), list):
            raise MaituAuthorityError("authoritative Maitu response does not prove a working/draft environment")
        status_value = room.get("status")
        if room.get("is_live") is True or status_value == 1:
            raise MaituAuthorityError("authoritative Maitu target is live")
        if room.get("is_live") is not False and (isinstance(status_value, bool) or status_value != 0):
            raise MaituAuthorityError("authoritative Maitu target is not positively confirmed non-live")
        return room

    def verify_checkpoint(
        self,
        checkpoint: dict[str, Any],
        evidence: dict[str, Any],
        *,
        expect_applied: bool = True,
    ) -> dict[str, Any]:
        live_room_id = str(evidence.get("target_live_room_id") or "").strip()
        if not live_room_id:
            raise MaituAuthorityError("checkpoint evidence has no target live room")
        room = self._read_working_room(live_room_id)
        clips = self._clips(room)
        operation_type = str(checkpoint.get("operation_type") or "")
        intent = checkpoint.get("intent_snapshot") if isinstance(checkpoint.get("intent_snapshot"), dict) else {}
        applied = False
        if operation_type == "preflight_content_build_plan":
            default_clip_id = evidence.get("default_clip_id")
            if default_clip_id is None:
                raise MaituAuthorityError("preflight evidence has no default clip identity")
            applied = bool(clips and self._same_id(clips[0].get("id"), default_clip_id))
        elif operation_type in {"fill_default_scene", "create_scene"}:
            expected_name = intent.get("scene_name")
            if not isinstance(expected_name, str) or not expected_name:
                raise MaituAuthorityError("scene intent has no intended scene name")
            if expect_applied:
                clip = self._find_by_id(clips, evidence.get("clip_id"))
                applied = clip is not None and clip.get("name") == expected_name
            elif operation_type == "fill_default_scene":
                applied = bool(clips and clips[0].get("name") == expected_name)
            else:
                applied = any(clip.get("name") == expected_name for clip in clips)
        elif operation_type in {"insert_asset_layer", "position_asset_layer"}:
            layer_name = intent.get("layer_id")
            if not isinstance(layer_name, str) or not layer_name:
                raise MaituAuthorityError("material intent has no layer identity")
            if expect_applied:
                clip = self._find_by_id(clips, evidence.get("clip_id"))
                material = self._find_by_id(self._materials(clip or {}), evidence.get("material_id"))
                candidates = [material] if material is not None else []
            else:
                target_clips = self._scene_candidates(clips, intent)
                if len(target_clips) > 1:
                    raise MaituAuthorityError("authoritative Maitu target scene is ambiguous")
                candidates = self._materials(target_clips[0]) if target_clips else []
            candidates = [
                material
                for material in candidates
                if material.get("name") == layer_name and self._material_source_matches(material, intent)
            ]
            if len(candidates) > 1:
                raise MaituAuthorityError("authoritative Maitu material effect is ambiguous")
            applied = len(candidates) == 1
            if applied and operation_type == "position_asset_layer":
                geometry_intent = {
                    "left": intent.get("x"),
                    "top": intent.get("y"),
                    "width": intent.get("width"),
                    "height": intent.get("height"),
                    "z_index": intent.get("z_index"),
                }
                applied = self._material_geometry_matches(candidates[0], geometry_intent)
        elif operation_type == "write_script":
            expected_text = intent.get("script_text")
            if not isinstance(expected_text, str):
                raise MaituAuthorityError("script intent has no authoritative text")
            if expect_applied:
                clip = self._find_by_id(clips, evidence.get("clip_id"))
                material = self._find_by_id(self._materials(clip or {}), evidence.get("text_material_id"))
                candidates = [material] if material is not None else []
            else:
                target_clips = self._scene_candidates(clips, intent)
                if len(target_clips) > 1:
                    raise MaituAuthorityError("authoritative Maitu target scene is ambiguous")
                candidates = self._materials(target_clips[0]) if target_clips else []
            matching_texts = [
                material
                for material in candidates
                if material is not None and material.get("type") == "text" and material.get("content") == expected_text
            ]
            if len(matching_texts) > 1:
                raise MaituAuthorityError("authoritative Maitu script effect is ambiguous")
            applied = len(matching_texts) == 1
        elif operation_type == "verify_scene":
            expected_layers = intent.get("expected_layers")
            verified_layers = evidence.get("verified_layers")
            if not isinstance(expected_layers, list) or not isinstance(verified_layers, list):
                raise MaituAuthorityError("verified scene has no authoritative layer set")
            clip = self._find_by_id(clips, evidence.get("clip_id"))
            materials = self._materials(clip or {})
            visuals = [material for material in materials if material.get("type") not in {"text", "audio"}]
            texts = [material for material in materials if material.get("type") == "text"]
            applied = (
                clip is not None
                and clip.get("name") == intent.get("scene_name")
                and len(visuals) == intent.get("expected_visual_count") == len(expected_layers)
                and len(texts) == intent.get("expected_text_count") == 1
                and len(verified_layers) == len(expected_layers)
            )
            if applied:
                for expected_layer in expected_layers:
                    if not isinstance(expected_layer, dict):
                        applied = False
                        break
                    dynamic = next(
                        (
                            layer
                            for layer in verified_layers
                            if isinstance(layer, dict)
                            and layer.get("layer_id") == expected_layer.get("layer_id")
                            and layer.get("asset_code") == expected_layer.get("asset_code")
                        ),
                        None,
                    )
                    material = self._find_by_id(visuals, (dynamic or {}).get("material_id"))
                    if (
                        material is None
                        or material.get("name") != expected_layer.get("layer_id")
                        or not self._material_source_matches(material, expected_layer)
                        or not self._material_geometry_matches(material, expected_layer)
                    ):
                        applied = False
                        break
            text = self._find_by_id(texts, evidence.get("text_material_id"))
            applied = (
                applied
                and text is not None
                and text.get("content") == intent.get("expected_script_text")
                and evidence.get("verified_script_text") == intent.get("expected_script_text")
            )
        else:
            raise MaituAuthorityError(f"operation {operation_type!r} has no backend authority policy")
        if applied is not expect_applied:
            expected_state = "applied" if expect_applied else "not applied"
            raise MaituAuthorityError(f"authoritative Maitu operation is not confirmed {expected_state}")
        observation = {
            "live_room_id": live_room_id,
            "operation_type": operation_type,
            "operation_applied": applied,
            "room_sha256": hashlib.sha256(self._canonical(room)).hexdigest(),
        }
        return observation

    def attest_completion(
        self,
        *,
        build_plan_code: str,
        execution_code: str,
        operation_index: int,
        checkpoint: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        evidence = dict(payload.get("evidence") or {})
        observation = self.verify_checkpoint(checkpoint, evidence)
        evidence["backend_authority_observation"] = observation
        unsigned_evidence = dict(evidence)
        attested = {
            "build_plan_code": build_plan_code,
            "execution_code": execution_code,
            "operation_index": operation_index,
            "operation_fingerprint": checkpoint["operation_fingerprint"],
            "attempt_id": str(payload["attempt_id"]),
            "lease_token": str(payload["lease_token"]),
            "lease_version": payload["lease_version"],
            "completion_id": str(payload["completion_id"]),
            "evidence": unsigned_evidence,
        }
        evidence["readback_attestation_algorithm"] = "hmac-sha256-v1"
        evidence["readback_attestation"] = self._sign(attested)
        return {**payload, "evidence": evidence}

    def attest_reconciliation(
        self,
        *,
        build_plan_code: str,
        execution_code: str,
        operation_index: int,
        checkpoint: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        evidence = dict(payload.get("evidence") or {})
        resolution = payload.get("resolution")
        expect_applied = resolution == "confirmed_completed"
        if resolution not in {"confirmed_completed", "confirmed_not_applied"}:
            raise MaituAuthorityError("reconciliation resolution has no backend authority policy")
        if evidence.get("operation_applied") is not expect_applied:
            raise MaituAuthorityError("reconciliation evidence contradicts the requested resolution")
        observation = self.verify_checkpoint(checkpoint, evidence, expect_applied=expect_applied)
        evidence["backend_authority_observation"] = observation
        unsigned_evidence = dict(evidence)
        attested = {
            "build_plan_code": build_plan_code,
            "execution_code": execution_code,
            "operation_index": operation_index,
            "operation_fingerprint": checkpoint["operation_fingerprint"],
            "reconciliation_id": str(payload["reconciliation_id"]),
            "reconciled_attempt_id": str(payload["reconciled_attempt_id"]),
            "resolution": payload["resolution"],
            "evidence": unsigned_evidence,
        }
        evidence["readback_attestation_algorithm"] = "hmac-sha256-v1"
        evidence["readback_attestation"] = self._sign(attested)
        return {**payload, "evidence": evidence}

    def attest_binding(self, asset_code: str, binding: dict[str, Any]) -> dict[str, Any]:
        regular = self._inventory("materials/?is_pub=false")
        digital_humans = self._inventory("materials/digital_human?access_rule=private")
        inventory = [*regular, *digital_humans]
        if binding.get("source_material_type") == "digital_human":
            item = next(
                (
                    candidate
                    for candidate in inventory
                    if self._same_id(candidate.get("speaker_id"), binding.get("speaker_id"))
                    and self._same_id(
                        candidate.get("digital_human_image_id"), binding.get("digital_human_image_id")
                    )
                ),
                None,
            )
        else:
            item = self._find_by_id(inventory, binding.get("maitu_material_id"))
        if item is None:
            raise MaituAuthorityError("material binding is absent from backend Maitu inventory readback")
        if str(item.get("type") or "") != str(binding.get("source_material_type") or ""):
            raise MaituAuthorityError("material binding type differs from backend Maitu inventory readback")
        if binding.get("source_material_type") == "digital_human":
            if not self._same_id(item.get("speaker_id"), binding.get("speaker_id")) or not self._same_id(
                item.get("digital_human_image_id"), binding.get("digital_human_image_id")
            ):
                raise MaituAuthorityError("digital-human binding differs from backend Maitu inventory readback")
            authoritative_binding = {
                "maitu_material_id": None,
                "source_material_type": "digital_human",
                "source_material_url": None,
                "source_cover_url": self._public_inventory_url(item.get("cover_url") or item.get("url"), required=False),
                "speaker_id": int(item["speaker_id"]),
                "digital_human_image_id": int(item["digital_human_image_id"]),
            }
        else:
            if str(item.get("url") or "") != str(binding.get("source_material_url") or ""):
                raise MaituAuthorityError("material binding URL differs from backend Maitu inventory readback")
            authoritative_binding = {
                "maitu_material_id": int(item["id"]),
                "source_material_type": str(item["type"]),
                "source_material_url": self._public_inventory_url(item.get("url"), required=True),
                "source_cover_url": self._public_inventory_url(
                    item.get("cover_url") or item.get("url"), required=False
                ),
                "speaker_id": None,
                "digital_human_image_id": None,
            }
        inventory_fingerprint = hashlib.sha256(self._canonical(item)).hexdigest()
        nonce = str(uuid4())
        attested = {
            "asset_code": asset_code,
            "binding": authoritative_binding,
            "inventory_snapshot_sha256": inventory_fingerprint,
            "readback_nonce": nonce,
        }
        return {
            **authoritative_binding,
            "inventory_snapshot_sha256": inventory_fingerprint,
            "readback_nonce": nonce,
            "readback_attestation": self._sign(attested),
        }

    def _inventory(self, base_path: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for offset in range(0, 10_000, 100):
            payload = self._get(f"{base_path}&offset={offset}&limit=100")
            if isinstance(payload, dict) and isinstance(payload.get("items"), list):
                batch = payload["items"]
            elif isinstance(payload, list):
                batch = payload
            else:
                raise MaituAuthorityError("backend Maitu inventory response schema is invalid")
            batch = [item for item in batch if isinstance(item, dict)]
            rows.extend(batch)
            if len(batch) < 100:
                return rows
        raise MaituAuthorityError("backend Maitu inventory pagination exceeded the safety limit")
