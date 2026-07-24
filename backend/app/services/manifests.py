from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

from app.domain.contracts import canonical_fingerprint, canonical_json_bytes
from app.domain.errors import DomainValidationError


RUN_MANIFEST_SCHEMA_VERSION = "run-manifest.v1"


REQUIRED_RUN_MANIFEST_KEYS = frozenset(
    {
        "input_revisions",
        "input_artifacts",
        "inventory_refs",
        "material_refs",
        "constraint_refs",
        "rights_refs",
        "template_refs",
        "fact_refs",
        "content_refs",
        "model_strategies",
        "prompt_revisions",
        "code_revision",
        "tool_versions",
        "random_seed",
        "environment",
    }
)


@dataclass(frozen=True, slots=True)
class SealedManifest:
    schema_version: str
    manifest: dict[str, Any]
    input_fingerprint: str
    output_fingerprint: str | None
    manifest_fingerprint: str
    signature_algorithm: str
    signature_key_id: str
    signature_value: str


def validate_run_manifest(manifest: dict[str, Any]) -> None:
    missing = sorted(REQUIRED_RUN_MANIFEST_KEYS - manifest.keys())
    unknown = sorted(manifest.keys() - REQUIRED_RUN_MANIFEST_KEYS)
    if missing or unknown:
        raise DomainValidationError(
            "RUN_MANIFEST_SCHEMA_INVALID",
            "RunManifest keys do not match run-manifest.v1",
            details={"missing": missing, "unknown": unknown},
        )
    for key in (
        "input_revisions",
        "input_artifacts",
        "inventory_refs",
        "material_refs",
        "constraint_refs",
        "rights_refs",
        "template_refs",
        "fact_refs",
        "content_refs",
        "model_strategies",
        "prompt_revisions",
        "tool_versions",
    ):
        if not isinstance(manifest[key], list):
            raise DomainValidationError(
                "RUN_MANIFEST_SCHEMA_INVALID",
                f"RunManifest {key} must be an array",
                details={"field": key},
            )
    if not isinstance(manifest["environment"], dict):
        raise DomainValidationError(
            "RUN_MANIFEST_SCHEMA_INVALID",
            "RunManifest environment must be an object",
            details={"field": "environment"},
        )


def seal_run_manifest(
    manifest: dict[str, Any],
    *,
    signing_key: bytes,
    key_id: str,
    output_refs: list[dict[str, Any]] | None = None,
) -> SealedManifest:
    if not signing_key:
        raise DomainValidationError("MANIFEST_SIGNING_KEY_MISSING", "A manifest signing key is required")
    if not key_id.strip():
        raise DomainValidationError("MANIFEST_SIGNING_KEY_ID_MISSING", "A signing key id is required")
    validate_run_manifest(manifest)
    normalized = dict(manifest)
    input_fingerprint = canonical_fingerprint(
        {
            "input_revisions": normalized["input_revisions"],
            "input_artifacts": normalized["input_artifacts"],
            "inventory_refs": normalized["inventory_refs"],
            "material_refs": normalized["material_refs"],
            "constraint_refs": normalized["constraint_refs"],
            "rights_refs": normalized["rights_refs"],
            "template_refs": normalized["template_refs"],
            "fact_refs": normalized["fact_refs"],
            "content_refs": normalized["content_refs"],
            "model_strategies": normalized["model_strategies"],
            "prompt_revisions": normalized["prompt_revisions"],
            "code_revision": normalized["code_revision"],
            "tool_versions": normalized["tool_versions"],
            "random_seed": normalized["random_seed"],
            "environment": normalized["environment"],
        }
    )
    output_fingerprint = canonical_fingerprint(output_refs) if output_refs is not None else None
    signed_payload = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "manifest": normalized,
        "input_fingerprint": input_fingerprint,
        "output_fingerprint": output_fingerprint,
    }
    manifest_fingerprint = canonical_fingerprint(signed_payload)
    signature = hmac.new(signing_key, canonical_json_bytes(signed_payload), hashlib.sha256).hexdigest()
    return SealedManifest(
        schema_version=RUN_MANIFEST_SCHEMA_VERSION,
        manifest=normalized,
        input_fingerprint=input_fingerprint,
        output_fingerprint=output_fingerprint,
        manifest_fingerprint=manifest_fingerprint,
        signature_algorithm="hmac-sha256",
        signature_key_id=key_id,
        signature_value=signature,
    )


def verify_sealed_manifest(sealed: SealedManifest, *, signing_key: bytes) -> bool:
    signed_payload = {
        "schema_version": sealed.schema_version,
        "manifest": sealed.manifest,
        "input_fingerprint": sealed.input_fingerprint,
        "output_fingerprint": sealed.output_fingerprint,
    }
    expected_fingerprint = canonical_fingerprint(signed_payload)
    expected_signature = hmac.new(signing_key, canonical_json_bytes(signed_payload), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sealed.manifest_fingerprint, expected_fingerprint) and hmac.compare_digest(
        sealed.signature_value,
        expected_signature,
    )


def explain_manifest_difference(left: SealedManifest, right: SealedManifest) -> dict[str, Any]:
    changed: list[str] = []
    for key in sorted(REQUIRED_RUN_MANIFEST_KEYS):
        if canonical_fingerprint(left.manifest[key]) != canonical_fingerprint(right.manifest[key]):
            changed.append(key)
    return {
        "same_input": left.input_fingerprint == right.input_fingerprint,
        "same_output": left.output_fingerprint == right.output_fingerprint,
        "same_manifest": left.manifest_fingerprint == right.manifest_fingerprint,
        "changed_sections": changed,
    }

