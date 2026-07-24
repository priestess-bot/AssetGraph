from __future__ import annotations

from typing import Any, Protocol


class ArtifactVerifier(Protocol):
    def verify_storage(self, artifact_code: str) -> dict[str, Any]: ...


class AlertRecorder(Protocol):
    def record_alert(self, **kwargs: Any) -> dict[str, Any]: ...


class EvidenceIntegrityMonitor:
    def __init__(self, alerts: AlertRecorder):
        self.alerts = alerts

    def verify_artifact(self, verifier: ArtifactVerifier, artifact_code: str) -> dict[str, Any]:
        result = verifier.verify_storage(artifact_code)
        if not result["valid"]:
            self.alerts.record_alert(
                alert_type="artifact_integrity",
                severity="critical",
                subject_type="artifact",
                subject_code=artifact_code,
                reason_code="ARTIFACT_STORAGE_INTEGRITY_INVALID",
                dedupe_key=f"artifact:{artifact_code}:storage-integrity",
                evidence=result,
            )
        return result
