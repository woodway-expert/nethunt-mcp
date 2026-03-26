from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class NethuntMCPError(Exception):
    code: str
    message: str
    status_code: int | None = None
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


class ConfigError(NethuntMCPError):
    """Raised when required environment configuration is missing or invalid."""


class ValidationError(NethuntMCPError):
    """Raised when tool input cannot be mapped to a supported NetHunt request."""
