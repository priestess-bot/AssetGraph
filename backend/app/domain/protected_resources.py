from __future__ import annotations

from typing import Any

from app.domain.contracts import Capability


def protected_resource_denial(
    resource: dict[str, Any] | None,
    capability: Capability | str,
) -> str | None:
    """Return the stable denial reason for an active protected resource."""
    if resource is None:
        return None
    capability_value = capability.value if isinstance(capability, Capability) else capability
    mode = str(resource.get("protection_mode") or "")
    if mode in {"read_only", "deny_write"}:
        return "PROTECTED_RESOURCE_DENY_WRITE"
    allowed = {str(value) for value in resource.get("allowed_capabilities") or []}
    if mode == "allowlisted_write" and capability_value not in allowed:
        return "PROTECTED_RESOURCE_CAPABILITY_DENIED"
    return None
