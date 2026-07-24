from __future__ import annotations

import hashlib
import hmac
from typing import Any

from app.domain.contracts import canonical_fingerprint, canonical_json_bytes
from app.domain.errors import DomainValidationError
from app.repositories.releases import ReleaseRepository


REQUIRED_SUBJECT_REFS = frozenset(
    {
        "content_project_revision",
        "production_variant_revision",
        "story_brief_revision",
        "script_revision",
        "program_revision",
        "shot_list_revision",
    }
)


class ReleaseService:
    def __init__(
        self,
        repository: ReleaseRepository,
        *,
        signing_key: bytes,
        signing_key_id: str,
    ) -> None:
        if not signing_key or not signing_key_id.strip():
            raise DomainValidationError("RELEASE_SIGNING_KEY_MISSING", "Release manifest signing key is required")
        self.repository = repository
        self.signing_key = signing_key
        self.signing_key_id = signing_key_id

    def create_candidate(
        self,
        *,
        subject_type: str,
        subject_code: str,
        subject_revision: int,
        carrier_kind: str,
        subject_refs: dict[str, Any],
        artifact_refs: list[dict[str, Any]],
        rights_snapshot: dict[str, Any],
        quality_snapshot: dict[str, Any],
        lineage_snapshot: dict[str, Any],
        carrier_facet: dict[str, Any],
        created_by: str,
    ) -> dict[str, Any]:
        manifest = {
            "schema_version": "release-manifest.v1",
            "carrier_kind": carrier_kind,
            "subject_refs": subject_refs,
            "artifact_refs": artifact_refs,
            "rights_snapshot": rights_snapshot,
            "quality_snapshot": quality_snapshot,
            "lineage_snapshot": lineage_snapshot,
            "carrier_facet": carrier_facet,
        }
        self._validate_structure(manifest)
        artifact_failures = self.repository.verify_artifact_refs(artifact_refs)
        if artifact_failures:
            raise DomainValidationError(
                "RELEASE_ARTIFACT_VALIDATION_FAILED",
                "Release artifact references could not be verified",
                details={"failures": artifact_failures},
            )
        fingerprint = canonical_fingerprint(manifest)
        signature = hmac.new(self.signing_key, canonical_json_bytes(manifest), hashlib.sha256).hexdigest()
        return self.repository.create_release_with_manifest(
            subject_type=subject_type,
            subject_code=subject_code,
            subject_revision=subject_revision,
            carrier_kind=carrier_kind,
            created_by=created_by,
            manifest=manifest,
            manifest_fingerprint=fingerprint,
            signature_algorithm="hmac-sha256",
            signature_key_id=self.signing_key_id,
            signature_value=signature,
        )

    def validate_candidate(self, release_code: str, *, actor_id: str) -> dict[str, Any]:
        release = self.repository.get_release(release_code)
        if release is None:
            raise KeyError(release_code)
        self.repository.transition_release(
            release_code,
            expected_status="candidate",
            target_status="validating",
            actor_id=actor_id,
            reason_code="VALIDATION_STARTED",
            evidence={"manifest_code": release["manifest"]["manifest_code"]},
        )
        manifest = release["manifest"]
        failures = self._gate_failures(manifest)
        if failures:
            self.repository.transition_release(
                release_code,
                expected_status="validating",
                target_status="candidate",
                actor_id=actor_id,
                reason_code="VALIDATION_FAILED",
                evidence={"failures": failures},
            )
            raise DomainValidationError(
                "RELEASE_GATE_FAILED",
                "Release candidate failed validation gates",
                details={"failures": failures},
            )
        return self.repository.transition_release(
            release_code,
            expected_status="validating",
            target_status="awaiting_approval",
            actor_id=actor_id,
            reason_code="VALIDATION_PASSED",
            evidence={"manifest_fingerprint": manifest["manifest_fingerprint"]},
        )

    def verify_manifest_signature(self, release_code: str) -> bool:
        release = self.repository.get_release(release_code)
        if release is None:
            raise KeyError(release_code)
        manifest_row = release["manifest"]
        manifest = {
            "schema_version": manifest_row["schema_version"],
            "carrier_kind": manifest_row["carrier_kind"],
            "subject_refs": manifest_row["subject_refs"],
            "artifact_refs": manifest_row["artifact_refs"],
            "rights_snapshot": manifest_row["rights_snapshot"],
            "quality_snapshot": manifest_row["quality_snapshot"],
            "lineage_snapshot": manifest_row["lineage_snapshot"],
            "carrier_facet": manifest_row["carrier_facet"],
        }
        expected_fingerprint = canonical_fingerprint(manifest)
        expected_signature = hmac.new(self.signing_key, canonical_json_bytes(manifest), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected_fingerprint, manifest_row["manifest_fingerprint"]) and hmac.compare_digest(
            expected_signature,
            manifest_row["signature_value"],
        )

    @staticmethod
    def _validate_structure(manifest: dict[str, Any]) -> None:
        if manifest["carrier_kind"] not in {"live_room_draft", "rendered_video"}:
            raise DomainValidationError("RELEASE_CARRIER_INVALID", "Unsupported release carrier kind")
        missing = sorted(REQUIRED_SUBJECT_REFS - manifest["subject_refs"].keys())
        if missing:
            raise DomainValidationError(
                "RELEASE_SUBJECT_REFS_INCOMPLETE",
                "Release manifest is missing required subject revisions",
                details={"missing": missing},
            )
        if ReleaseService._contains_latest(manifest):
            raise DomainValidationError(
                "RELEASE_LATEST_REFERENCE_FORBIDDEN",
                "Release manifests must reference exact immutable revisions",
            )
        required_facet = {
            "live_room_draft": "build_plan_ref",
            "rendered_video": "production_timeline_ref",
        }[manifest["carrier_kind"]]
        if required_facet not in manifest["carrier_facet"]:
            raise DomainValidationError(
                "RELEASE_CARRIER_FACET_INCOMPLETE",
                f"Release carrier facet requires {required_facet}",
            )

    @staticmethod
    def _gate_failures(manifest: dict[str, Any]) -> list[str]:
        failures: list[str] = []
        if manifest["rights_snapshot"].get("status") != "valid":
            failures.append("RIGHTS_NOT_VALID")
        if not manifest["lineage_snapshot"].get("complete"):
            failures.append("LINEAGE_INCOMPLETE")
        gates = manifest["quality_snapshot"].get("gates") or []
        if not isinstance(gates, list) or not gates:
            failures.append("QUALITY_GATES_MISSING")
        else:
            for gate in gates:
                if not isinstance(gate, dict):
                    failures.append("QUALITY_GATE_INVALID")
                elif gate.get("blocking", True) and gate.get("status") != "pass":
                    failures.append(f"QUALITY_GATE_BLOCKED:{gate.get('code', 'unknown')}")
        failures.extend(ReleaseService._artifact_ref_failures(manifest["artifact_refs"]))
        return sorted(set(failures))

    @staticmethod
    def _artifact_ref_failures(artifact_refs: list[dict[str, Any]]) -> list[str]:
        failures: list[str] = []
        if not artifact_refs:
            return ["ARTIFACT_REFS_MISSING"]
        for reference in artifact_refs:
            checksum = reference.get("checksum_sha256")
            if not reference.get("artifact_code") or not isinstance(checksum, str) or len(checksum) != 64:
                failures.append("ARTIFACT_REFERENCE_INCOMPLETE")
        return failures

    @staticmethod
    def _contains_latest(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() == "latest"
        if isinstance(value, dict):
            return any(ReleaseService._contains_latest(key) or ReleaseService._contains_latest(item) for key, item in value.items())
        if isinstance(value, (list, tuple)):
            return any(ReleaseService._contains_latest(item) for item in value)
        return False
