from __future__ import annotations

from typing import Any


class DomainError(RuntimeError):
    """Base error with a stable machine-readable rule code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class DomainValidationError(DomainError):
    pass


class DomainConflictError(DomainError):
    pass


class DomainAuthorizationError(DomainError):
    pass


class DomainUnavailableError(DomainError):
    pass

