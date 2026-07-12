from __future__ import annotations

import copy
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urlparse


class AssetBindingClient(Protocol):
    def get_asset(self, asset_code: str) -> dict[str, Any] | None:
        """Read one AssetGraph asset."""

    def update_asset_maitu_material_binding(self, asset_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist a verified Maitu material binding."""


class MaituMaterialSession(Protocol):
    def list_maitu_materials(self) -> list[dict[str, Any]]:
        """Read private regular and digital-human material records."""

    def upload_maitu_material(
        self,
        *,
        asset: dict[str, Any],
        local_path: Path,
        layer_type: str | None,
    ) -> dict[str, Any]:
        """Upload one local asset and return the created Maitu material record."""


@dataclass(slots=True)
class MaituMaterialResolutionIssue:
    asset_code: str
    reason: str
    summary: str
    candidate_material_ids: list[int]


@dataclass(slots=True)
class MaituMaterialResolutionResult:
    status: str
    reused_binding_count: int
    remote_match_count: int
    uploaded_count: int
    manual_required_count: int
    operation_plan: dict[str, Any]
    issues: list[MaituMaterialResolutionIssue]


class MaituMaterialResolver:
    """Resolve AssetGraph selections to real Maitu materials before draft build.

    Resolution is fail-closed: an ambiguous remote match, missing local file, or
    upload failure never invents a material ID or URL. Verified bindings are
    written back to AssetGraph and propagated to every operation for the asset.
    """

    BINDING_FIELDS = (
        "maitu_material_id",
        "source_material_type",
        "source_material_url",
        "source_cover_url",
        "speaker_id",
        "digital_human_image_id",
    )
    IMAGE_LAYER_TYPES = {
        "background_image",
        "product_image",
        "promotion_sticker",
        "brand_logo_title",
    }
    VISUAL_LAYER_TYPES = {"supporting_visual"}
    VIDEO_LAYER_TYPES = {"product_video"}
    DIGITAL_HUMAN_LAYER_TYPES = {"digital_human"}
    SUPPORTED_PLAN_OPERATION_TYPES = {
        "preflight_content_build_plan",
        "fill_default_scene",
        "create_scene",
        "insert_asset_layer",
        "position_asset_layer",
        "placeholder_required",
        "write_script",
        "verify_scene",
        "save_draft",
    }

    def __init__(
        self,
        *,
        asset_client: AssetBindingClient,
        session: MaituMaterialSession,
        assets_root: str | Path,
    ) -> None:
        self.asset_client = asset_client
        self.session = session
        self.assets_root = Path(assets_root)

    def resolve_plan(self, operation_plan: dict[str, Any]) -> MaituMaterialResolutionResult:
        if not isinstance(operation_plan, dict):
            resolved_plan: dict[str, Any] = {"operations": []}
            issue = self._issue("", "invalid_material_operation_plan", "BuildPlan must be a JSON object.")
            return self._result(resolved_plan, issues=[issue])
        resolved_plan = copy.deepcopy(operation_plan)
        raw_operations = resolved_plan.get("operations")
        if not isinstance(raw_operations, list):
            resolved_plan["operations"] = []
            issue = self._issue("", "invalid_material_operation_plan", "BuildPlan operations must be a list.")
            return self._result(resolved_plan, issues=[issue])
        operations = raw_operations
        validation_issues = self._validate_operation_plan(operations)
        if validation_issues:
            return self._result(resolved_plan, issues=validation_issues)

        targets = self._resolution_targets(operations)
        resolutions: dict[str, tuple[dict[str, Any], str]] = {}
        upload_intents: list[tuple[str, str, dict[str, Any], Path]] = []
        issues: list[MaituMaterialResolutionIssue] = []
        inventory: list[dict[str, Any]] | None = None
        reused_binding_count = 0
        remote_match_count = 0
        uploaded_count = 0

        # Preflight every asset before any Maitu upload or AssetGraph binding write.
        for asset_code, layer_type in targets:
            try:
                asset = self.asset_client.get_asset(asset_code)
            except Exception as exc:  # pragma: no cover - runtime boundary
                issues.append(self._issue(asset_code, "asset_lookup_failed", f"AssetGraph asset lookup failed safely: {exc}"))
                continue
            if asset is None:
                issues.append(self._issue(asset_code, "asset_not_found", "AssetGraph asset was not found; material resolution was skipped."))
                continue
            if not isinstance(asset, dict) or str(asset.get("asset_code") or "").strip() != asset_code:
                issues.append(
                    self._issue(
                        asset_code,
                        "invalid_asset_response",
                        "AssetGraph returned an invalid or mismatched asset record; material resolution was skipped.",
                    )
                )
                continue
            if asset.get("maitu_category") == "digital_human_video" and self._layer_kind(layer_type) != "digital_human":
                issues.append(
                    self._issue(
                        asset_code,
                        "digital_human_asset_layer_mismatch",
                        "A digital-human training asset cannot be resolved or uploaded as a regular image/video layer.",
                    )
                )
                continue

            binding = self._binding_from_asset(asset)
            if self._has_executable_binding(binding, layer_type=layer_type, asset=asset):
                stored_material_id = binding.get("maitu_material_id")
                if stored_material_id is None:
                    resolutions[asset_code] = (binding, "reused_assetgraph_binding")
                    reused_binding_count += 1
                    continue
                if inventory is None:
                    try:
                        inventory = self._load_inventory()
                    except Exception as exc:  # pragma: no cover - runtime boundary
                        issues.append(self._issue(asset_code, "maitu_inventory_lookup_failed", f"Maitu inventory lookup failed safely: {exc}"))
                        continue
                stored_matches = [
                    material
                    for material in inventory
                    if str(material.get("id") or "") == str(stored_material_id)
                    and self._type_compatible(
                        layer_type,
                        material.get("type"),
                        digital_human=self._is_digital_human(layer_type, asset),
                    )
                ]
                stored_selected, stored_ambiguous, stored_ids = self._select_unambiguous(stored_matches)
                if stored_ambiguous:
                    issues.append(
                        self._issue(
                            asset_code,
                            "ambiguous_stored_maitu_material",
                            "The stored Maitu material ID resolved to conflicting inventory records; refusing to guess.",
                            candidate_material_ids=stored_ids,
                        )
                    )
                    continue
                if stored_selected is not None:
                    authoritative_binding = self._binding_from_material(stored_selected)
                    if self._has_executable_binding(authoritative_binding, layer_type=layer_type, asset=asset):
                        executable_fields = {
                            field: authoritative_binding[field]
                            for field in (
                                "maitu_material_id",
                                "source_material_type",
                                "source_material_url",
                                "speaker_id",
                                "digital_human_image_id",
                            )
                            if field in authoritative_binding
                        }
                        if self._persisted_binding_matches(executable_fields, asset):
                            resolutions[asset_code] = (authoritative_binding, "reused_assetgraph_binding")
                            reused_binding_count += 1
                        else:
                            resolutions[asset_code] = (authoritative_binding, "matched_existing_maitu_material")
                            remote_match_count += 1
                        continue

            if inventory is None:
                try:
                    inventory = self._load_inventory()
                except Exception as exc:  # pragma: no cover - runtime boundary
                    issues.append(self._issue(asset_code, "maitu_inventory_lookup_failed", f"Maitu inventory lookup failed safely: {exc}"))
                    continue
            matches = self._matching_materials(asset, layer_type, inventory)
            selected, ambiguous, ambiguous_ids = self._select_unambiguous(matches)
            if ambiguous:
                issues.append(
                    self._issue(
                        asset_code,
                        "ambiguous_maitu_material_match",
                        "Multiple Maitu material records matched; refusing to guess even when URLs are shared.",
                        candidate_material_ids=ambiguous_ids,
                    )
                )
                continue
            if selected is not None:
                binding = self._binding_from_material(selected)
                if not self._has_executable_binding(binding, layer_type=layer_type, asset=asset):
                    issues.append(self._issue(asset_code, "invalid_maitu_material_binding", "Matched Maitu material is incomplete or incompatible."))
                    continue
                resolutions[asset_code] = (binding, "matched_existing_maitu_material")
                remote_match_count += 1
                continue
            if self._is_digital_human(layer_type, asset):
                issues.append(
                    self._issue(
                        asset_code,
                        "digital_human_material_not_found",
                        "No existing Maitu digital-human model matched; a local training video cannot be uploaded as an executable digital human.",
                    )
                )
                continue
            local_path = self._safe_local_path(asset)
            if local_path is None or not local_path.is_file():
                issues.append(
                    self._issue(
                        asset_code,
                        "local_asset_file_not_found",
                        "No existing Maitu material matched and the AssetGraph local file was not found.",
                    )
                )
                continue
            if not self._local_file_matches_layer(local_path, layer_type):
                issues.append(
                    self._issue(
                        asset_code,
                        "local_asset_type_mismatch",
                        "The local file extension is unsupported or incompatible with the planned image/video layer type.",
                    )
                )
                continue
            if not self._normalize_name(local_path.name):
                issues.append(
                    self._issue(
                        asset_code,
                        "local_asset_filename_unmatchable",
                        "The local filename has no stable key for authoritative Maitu upload readback.",
                    )
                )
                continue
            upload_intents.append((asset_code, layer_type, asset, local_path))

        if issues:
            self._mark_issues_manual(operations, issues)
            return self._result(
                resolved_plan,
                reused_binding_count=reused_binding_count,
                remote_match_count=remote_match_count,
                issues=issues,
            )

        if upload_intents:
            issues.extend(
                self._issue(
                    asset_code,
                    "fenced_material_preparation_required",
                    (
                        "No existing Maitu material matched. Automatic upload is disabled until "
                        "material preparation is covered by a durable dispatched checkpoint."
                    ),
                )
                for asset_code, _layer_type, _asset, _local_path in upload_intents
            )
            self._mark_issues_manual(operations, issues)
            return self._result(
                resolved_plan,
                reused_binding_count=reused_binding_count,
                remote_match_count=remote_match_count,
                uploaded_count=0,
                issues=issues,
            )

        for asset_code, layer_type in targets:
            binding, resolution_status = resolutions[asset_code]
            try:
                persisted = self.asset_client.update_asset_maitu_material_binding(asset_code, binding)
            except Exception as exc:  # pragma: no cover - runtime boundary
                issues.append(self._issue(asset_code, "binding_writeback_failed", f"AssetGraph binding write-back failed safely: {exc}"))
                break
            persisted_binding = self._binding_from_asset(persisted) if isinstance(persisted, dict) else {}
            critical_fields = (
                "maitu_material_id",
                "source_material_type",
                "source_material_url",
                "speaker_id",
                "digital_human_image_id",
            )
            if (
                not isinstance(persisted, dict)
                or str(persisted.get("asset_code") or "").strip() != asset_code
                or persisted.get("maitu_binding_verification_source") != "backend_maitu_inventory_readback"
                or persisted.get("maitu_binding_scope") != "assetgraph_script_layout_material_binding_v2"
                or not persisted.get("maitu_binding_verified_at")
                or any(persisted_binding.get(field) != binding.get(field) for field in critical_fields)
                or not self._has_executable_binding(persisted_binding, layer_type=layer_type, asset=persisted)
            ):
                issues.append(
                    self._issue(
                        asset_code,
                        "binding_writeback_verification_failed",
                        "AssetGraph binding write-back response did not return a complete backend-authoritative binding receipt.",
                    )
                )
                break
            binding = persisted_binding
            resolutions[asset_code] = (binding, resolution_status)
            self._apply_binding(operations, asset_code, binding, resolution_status)

        if issues:
            self._mark_issues_manual(operations, issues)
        return self._result(
            resolved_plan,
            reused_binding_count=reused_binding_count,
            remote_match_count=remote_match_count,
            uploaded_count=uploaded_count,
            issues=issues,
        )

    @classmethod
    def _validate_operation_plan(cls, operations: list[Any]) -> list[MaituMaterialResolutionIssue]:
        issues: list[MaituMaterialResolutionIssue] = []
        operation_kinds: dict[str, set[str]] = {}
        insert_codes: set[str] = set()
        for operation in operations:
            if not isinstance(operation, dict):
                issues.append(cls._issue("", "invalid_material_operation_plan", "BuildPlan operation entries must be objects."))
                continue
            raw_operation_type = operation.get("operation_type")
            if (
                not isinstance(raw_operation_type, str)
                or not raw_operation_type.strip()
                or raw_operation_type != raw_operation_type.strip()
            ):
                issues.append(cls._issue("", "invalid_material_operation_plan", "BuildPlan operation_type must be a canonical non-empty string."))
                continue
            operation_type = raw_operation_type.strip()
            if operation_type not in cls.SUPPORTED_PLAN_OPERATION_TYPES:
                issues.append(
                    cls._issue(
                        "",
                        "invalid_material_operation_plan",
                        f"Unsupported BuildPlan operation_type {operation_type!r}; refusing plan-wide execution.",
                    )
                )
                continue
            if operation_type == "placeholder_required" and bool(operation.get("blocks_execution", True)):
                issues.append(
                    cls._issue(
                        "",
                        "unresolved_material_placeholder",
                        "BuildPlan contains a blocking material placeholder; refusing all draft mutations.",
                    )
                )
                continue
            if operation_type not in {"insert_asset_layer", "position_asset_layer"}:
                continue
            raw_asset_code = operation.get("asset_code")
            raw_layer_type = operation.get("layer_type")
            asset_code = raw_asset_code.strip() if isinstance(raw_asset_code, str) else ""
            layer_type = raw_layer_type.strip() if isinstance(raw_layer_type, str) else ""
            kind = cls._layer_kind(layer_type)
            if (
                raw_asset_code != asset_code
                or raw_layer_type != layer_type
                or not re.fullmatch(r"[A-Za-z0-9_-]+", asset_code)
                or kind is None
            ):
                issues.append(
                    cls._issue(
                        asset_code,
                        "invalid_material_operation_plan",
                        f"{operation_type} requires a safe non-empty string asset_code and supported string layer_type.",
                    )
                )
                continue
            operation_kinds.setdefault(asset_code, set()).add(kind)
            if operation_type == "insert_asset_layer":
                insert_codes.add(asset_code)
        for asset_code, kinds in operation_kinds.items():
            compatible_visual_mix = kinds <= {"visual", "image"} or kinds <= {"visual", "video"}
            if len(kinds) > 1 and not compatible_visual_mix:
                issues.append(
                    cls._issue(
                        asset_code,
                        "conflicting_asset_layer_types",
                        "One asset_code is used by incompatible image/video/digital-human insert operations.",
                    )
                )
        for operation in operations:
            if not isinstance(operation, dict) or operation.get("operation_type") != "position_asset_layer":
                continue
            asset_code = str(operation.get("asset_code") or "").strip()
            if asset_code and asset_code not in insert_codes:
                issues.append(
                    cls._issue(
                        asset_code,
                        "position_without_insert_operation",
                        "Position operation references an asset with no corresponding insert operation.",
                    )
                )
        return issues

    @classmethod
    def _resolution_targets(cls, operations: list[Any]) -> list[tuple[str, str]]:
        target_by_asset: dict[str, str] = {}
        order: list[str] = []
        for operation in operations:
            if not isinstance(operation, dict) or operation.get("operation_type") != "insert_asset_layer":
                continue
            asset_code = str(operation.get("asset_code") or "").strip()
            if asset_code and asset_code not in target_by_asset:
                target_by_asset[asset_code] = str(operation.get("layer_type") or "").strip()
                order.append(asset_code)
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            asset_code = str(operation.get("asset_code") or "").strip()
            if asset_code not in target_by_asset:
                continue
            layer_type = str(operation.get("layer_type") or "").strip()
            current_kind = cls._layer_kind(target_by_asset[asset_code])
            new_kind = cls._layer_kind(layer_type)
            if current_kind == "visual" and new_kind in {"image", "video"}:
                target_by_asset[asset_code] = layer_type
        return [(asset_code, target_by_asset[asset_code]) for asset_code in order]

    @classmethod
    def _binding_from_asset(cls, asset: dict[str, Any]) -> dict[str, Any]:
        return {field: asset.get(field) for field in cls.BINDING_FIELDS}

    @classmethod
    def _binding_from_material(cls, material: dict[str, Any]) -> dict[str, Any]:
        source_type = material.get("type") or material.get("source_material_type")
        is_digital_human = str(source_type or "").strip().lower() == "digital_human"
        values = {
            "maitu_material_id": None if is_digital_human else material.get("id") or material.get("material_id"),
            "source_material_type": source_type,
            "source_material_url": None
            if is_digital_human
            else material.get("url") or material.get("source_material_url"),
            "source_cover_url": material.get("cover_url") or material.get("source_cover_url"),
            "speaker_id": material.get("speaker_id"),
            "digital_human_image_id": material.get("digital_human_image_id"),
        }
        return values

    @classmethod
    def _has_executable_binding(
        cls,
        binding: dict[str, Any],
        *,
        layer_type: str | None,
        asset: dict[str, Any],
    ) -> bool:
        digital_human = cls._is_digital_human(layer_type, asset)
        source_type = str(binding.get("source_material_type") or "").lower()
        if not source_type:
            return False
        if not cls._type_compatible(layer_type, source_type, digital_human=digital_human):
            return False
        if digital_human:
            return cls._positive_int(binding.get("speaker_id")) is not None and cls._positive_int(
                binding.get("digital_human_image_id")
            ) is not None
        return cls._positive_int(binding.get("maitu_material_id")) is not None and cls._is_https_url(
            binding.get("source_material_url")
        )

    @classmethod
    def operation_has_executable_binding(cls, operation: Any) -> bool:
        if not isinstance(operation, dict):
            return False
        return cls._has_executable_binding(
            operation,
            layer_type=operation.get("layer_type"),
            asset=operation,
        )

    def _load_inventory(self) -> list[dict[str, Any]]:
        inventory = self.session.list_maitu_materials()
        if not isinstance(inventory, list):
            raise ValueError("Maitu inventory must be a list")
        validated: list[dict[str, Any]] = []
        for index, material in enumerate(inventory):
            if not isinstance(material, dict):
                raise ValueError(f"Maitu inventory record {index} must be an object")
            if self._positive_int(material.get("id")) is None:
                raise ValueError(f"Maitu inventory record {index} has an invalid material id")
            if not str(material.get("type") or "").strip():
                raise ValueError(f"Maitu inventory record {index} has no material type")
            validated.append(material)
        return validated

    def _matching_materials(
        self,
        asset: dict[str, Any],
        layer_type: str | None,
        inventory: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        asset_keys = self._asset_match_keys(asset)
        filename_keys = {
            key
            for value in (asset.get("original_filename"), Path(str(asset.get("local_relative_path") or "")).name)
            if (key := self._normalize_name(value))
        }
        digital_human = self._is_digital_human(layer_type, asset)
        matches: list[dict[str, Any]] = []
        for material in inventory:
            if not self._type_compatible(layer_type, material.get("type"), digital_human=digital_human):
                continue
            material_keys = self._material_match_keys(material)
            exact = bool(asset_keys.intersection(material_keys))
            uploaded_filename_match = not digital_human and any(
                re.fullmatch(re.escape(filename_key) + r"\d{3,4}", material_key)
                for filename_key in filename_keys
                for material_key in material_keys
                if filename_key and material_key
            )
            nested_digital_human = digital_human and any(
                material_key and len(material_key) >= 4 and any(material_key in asset_key for asset_key in asset_keys)
                for material_key in material_keys
            )
            if exact or uploaded_filename_match or nested_digital_human:
                matches.append(material)
        return matches

    @classmethod
    def _asset_match_keys(cls, asset: dict[str, Any]) -> set[str]:
        values = [
            asset.get("subject"),
            asset.get("original_filename"),
            asset.get("title"),
            Path(str(asset.get("local_relative_path") or "")).name,
        ]
        title = str(asset.get("title") or "")
        if " - " in title:
            values.append(title.rsplit(" - ", 1)[-1])
        return {key for value in values if (key := cls._normalize_name(value))}

    @classmethod
    def _material_match_keys(cls, material: dict[str, Any]) -> set[str]:
        nested_image = material.get("digital_human_image") if isinstance(material.get("digital_human_image"), dict) else {}
        values = [
            material.get("name"),
            cls._url_basename(material.get("url")),
            nested_image.get("name"),
            nested_image.get("code"),
            material.get("digital_human_image_id"),
            nested_image.get("id"),
        ]
        return {key for value in values if (key := cls._normalize_name(value))}

    @classmethod
    def _layer_kind(cls, layer_type: str | None) -> str | None:
        normalized = str(layer_type or "").strip().lower()
        if normalized in cls.IMAGE_LAYER_TYPES:
            return "image"
        if normalized in cls.VISUAL_LAYER_TYPES:
            return "visual"
        if normalized in cls.VIDEO_LAYER_TYPES:
            return "video"
        if normalized in cls.DIGITAL_HUMAN_LAYER_TYPES:
            return "digital_human"
        return None

    @classmethod
    def _is_digital_human(cls, layer_type: str | None, asset: dict[str, Any]) -> bool:
        del asset
        return cls._layer_kind(layer_type) == "digital_human"

    @classmethod
    def _type_compatible(cls, layer_type: str | None, material_type: Any, *, digital_human: bool) -> bool:
        remote_type = str(material_type or "").strip().lower()
        planned_kind = "digital_human" if digital_human else cls._layer_kind(layer_type)
        if planned_kind == "digital_human":
            return remote_type == "digital_human"
        if planned_kind == "video":
            return remote_type in {"video", "decorative_video"}
        if planned_kind == "visual":
            return remote_type in {"image", "video", "decorative_video"}
        if planned_kind == "image":
            return remote_type == "image"
        return False

    @staticmethod
    def _select_unambiguous(matches: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, bool, list[int]]:
        if not matches:
            return None, False, []
        if len(matches) == 1:
            return matches[0], False, []
        ids: list[int] = []
        every_match_has_numeric_id = True
        for item in matches:
            try:
                if item.get("id") is None:
                    every_match_has_numeric_id = False
                else:
                    ids.append(int(item["id"]))
            except (TypeError, ValueError):
                every_match_has_numeric_id = False
        unique_ids = sorted(set(ids))
        if every_match_has_numeric_id and len(unique_ids) == 1:
            identity_fields = ("type", "url", "speaker_id", "digital_human_image_id")
            conflicting_identity = any(
                len({str(item.get(field)) for item in matches if item.get(field) not in {None, ""}}) > 1
                for field in identity_fields
            )
            if conflicting_identity:
                return None, True, unique_ids
            selected = max(matches, key=lambda item: sum(value is not None and value != "" for value in item.values()))
            return selected, False, []
        return None, True, unique_ids

    def _safe_local_path(self, asset: dict[str, Any]) -> Path | None:
        relative = str(asset.get("local_relative_path") or "").strip()
        if not relative:
            return None
        root = self.assets_root.resolve()
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return candidate

    @classmethod
    def _local_file_matches_layer(cls, path: Path, layer_type: str | None) -> bool:
        suffix = path.suffix.lower()
        kind = cls._layer_kind(layer_type)
        if kind == "image":
            return suffix in {".png", ".jpg", ".jpeg", ".gif"}
        if kind == "video":
            return suffix in {".mp4", ".mov", ".m4v", ".avi"}
        if kind == "visual":
            return suffix in {".png", ".jpg", ".jpeg", ".gif", ".mp4", ".mov", ".m4v", ".avi"}
        return False

    @classmethod
    def _persisted_binding_matches(cls, expected: dict[str, Any], persisted_asset: dict[str, Any]) -> bool:
        actual = cls._binding_from_asset(persisted_asset)
        for field, expected_value in expected.items():
            actual_value = actual.get(field)
            if expected_value is None:
                if actual_value is not None:
                    return False
                continue
            if field in {"maitu_material_id", "speaker_id", "digital_human_image_id"}:
                try:
                    if int(actual_value) != int(expected_value):
                        return False
                except (TypeError, ValueError):
                    return False
            elif actual_value != expected_value:
                return False
        return True

    @classmethod
    def _mark_issues_manual(cls, operations: list[Any], issues: list[MaituMaterialResolutionIssue]) -> None:
        for issue in issues:
            if issue.asset_code:
                cls._mark_manual_required(operations, issue.asset_code, issue.reason)

    @staticmethod
    def _result(
        operation_plan: dict[str, Any],
        *,
        reused_binding_count: int = 0,
        remote_match_count: int = 0,
        uploaded_count: int = 0,
        issues: list[MaituMaterialResolutionIssue] | None = None,
    ) -> MaituMaterialResolutionResult:
        result_issues = issues or []
        status = "resolved" if not result_issues else "completed_with_manual_review"
        operation_plan["material_resolution"] = {
            "status": status,
            "reused_binding_count": reused_binding_count,
            "remote_match_count": remote_match_count,
            "uploaded_count": uploaded_count,
            "manual_required_count": len(result_issues),
        }
        return MaituMaterialResolutionResult(
            status=status,
            reused_binding_count=reused_binding_count,
            remote_match_count=remote_match_count,
            uploaded_count=uploaded_count,
            manual_required_count=len(result_issues),
            operation_plan=operation_plan,
            issues=result_issues,
        )

    @classmethod
    def _apply_binding(
        cls,
        operations: list[Any],
        asset_code: str,
        binding: dict[str, Any],
        resolution_status: str,
    ) -> None:
        for operation in operations:
            if not isinstance(operation, dict) or operation.get("asset_code") != asset_code:
                continue
            operation.update(binding)
            # ``material_id`` is the executor alias for the authoritative
            # regular-material ID. Set it even when null so a digital-human
            # binding cannot retain a stale regular material identity from the
            # source BuildPlan.
            operation["material_id"] = binding.get("maitu_material_id")
            operation["material_resolution_status"] = resolution_status
            operation.pop("material_resolution_reason", None)

    @staticmethod
    def _mark_manual_required(operations: list[Any], asset_code: str, reason: str) -> None:
        for operation in operations:
            if not isinstance(operation, dict) or operation.get("asset_code") != asset_code:
                continue
            operation["material_resolution_status"] = "manual_required"
            operation["material_resolution_reason"] = reason

    @staticmethod
    def _issue(
        asset_code: str,
        reason: str,
        summary: str,
        *,
        candidate_material_ids: list[int] | None = None,
    ) -> MaituMaterialResolutionIssue:
        return MaituMaterialResolutionIssue(
            asset_code=asset_code,
            reason=reason,
            summary=summary,
            candidate_material_ids=candidate_material_ids or [],
        )

    @staticmethod
    def _positive_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 and str(value).strip() == str(parsed) else None

    @staticmethod
    def _is_https_url(value: Any) -> bool:
        parsed = urlparse(str(value or "").strip())
        return parsed.scheme.lower() == "https" and bool(parsed.netloc)

    @staticmethod
    def _url_basename(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return Path(unquote(urlparse(text).path)).name

    @staticmethod
    def _normalize_name(value: Any) -> str:
        text = unicodedata.normalize("NFKC", unquote(str(value or ""))).strip().lower()
        if not text:
            return ""
        text = Path(text).name
        text = re.sub(r"\.(?:png|jpe?g|gif|webp|mp4|mov|m4v|avi|wav|mp3)$", "", text, flags=re.IGNORECASE)
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)
