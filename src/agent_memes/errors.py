"""Structured errors. Every failure an agent can hit has a stable ``code`` and a ``hint``."""

from __future__ import annotations

from typing import Any

# code -> CLI exit status
EXIT_CODES = {
    "invalid_input": 2,
    "missing_api_key": 3,
    "auth_failed": 3,
    "not_found": 4,
    "ffmpeg_missing": 5,
    "ffmpeg_failed": 5,
    "rate_limited": 6,
    "network_error": 7,
    "upstream_error": 7,
}


class MemeError(Exception):
    """An error with a machine-readable code, a human message and an actionable hint."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "error",
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint
        self.details = details or {}

    @property
    def exit_code(self) -> int:
        return EXIT_CODES.get(self.code, 1)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.hint:
            out["hint"] = self.hint
        if self.details:
            out["details"] = self.details
        return out


def invalid(message: str, hint: str | None = None) -> MemeError:
    return MemeError(message, code="invalid_input", hint=hint)
