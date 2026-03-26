from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from typing import Mapping

from .errors import ConfigError

DEFAULT_BASE_URL = "https://nethunt.com"
DEFAULT_TIMEZONE = "Europe/Kiev"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_TRANSPORT = "stdio"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_TIMEOUT_SECONDS = 15.0
SUPPORTED_TRANSPORTS = {"stdio", "streamable-http"}


@dataclass(slots=True, frozen=True)
class Settings:
    nethunt_email: str
    nethunt_api_key: str = field(repr=False)
    nethunt_base_url: str = DEFAULT_BASE_URL
    nethunt_timezone: str = DEFAULT_TIMEZONE
    nethunt_log_level: str = DEFAULT_LOG_LEVEL
    mcp_transport: str = DEFAULT_TRANSPORT
    mcp_host: str = DEFAULT_HOST
    mcp_port: int = DEFAULT_PORT
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @property
    def api_base_url(self) -> str:
        return f"{self.nethunt_base_url.rstrip('/')}/api/v1/zapier"

    @property
    def basic_auth_header_value(self) -> str:
        token = f"{self.nethunt_email}:{self.nethunt_api_key}".encode("utf-8")
        return f"Basic {base64.b64encode(token).decode('ascii')}"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        values = env or os.environ
        email = values.get("NETHUNT_EMAIL", "").strip()
        api_key = values.get("NETHUNT_API_KEY", "").strip()
        if not email:
            raise ConfigError(code="config_error", message="NETHUNT_EMAIL is required.")
        if not api_key:
            raise ConfigError(code="config_error", message="NETHUNT_API_KEY is required.")

        mcp_transport = values.get("MCP_TRANSPORT", DEFAULT_TRANSPORT).strip() or DEFAULT_TRANSPORT
        if mcp_transport not in SUPPORTED_TRANSPORTS:
            raise ConfigError(
                code="config_error",
                message=f"MCP_TRANSPORT must be one of: {', '.join(sorted(SUPPORTED_TRANSPORTS))}.",
                details={"value": mcp_transport},
            )

        try:
            mcp_port = int(values.get("MCP_PORT", str(DEFAULT_PORT)))
        except ValueError as exc:
            raise ConfigError(
                code="config_error",
                message="MCP_PORT must be an integer.",
                details={"value": values.get("MCP_PORT")},
            ) from exc

        if not 1 <= mcp_port <= 65535:
            raise ConfigError(
                code="config_error",
                message="MCP_PORT must be between 1 and 65535.",
                details={"value": mcp_port},
            )

        nethunt_base_url = values.get("NETHUNT_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
        if not nethunt_base_url.startswith(("http://", "https://")):
            raise ConfigError(
                code="config_error",
                message="NETHUNT_BASE_URL must start with http:// or https://.",
                details={"value": nethunt_base_url},
            )

        return cls(
            nethunt_email=email,
            nethunt_api_key=api_key,
            nethunt_base_url=nethunt_base_url.rstrip("/"),
            nethunt_timezone=values.get("NETHUNT_TIMEZONE", DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE,
            nethunt_log_level=values.get("NETHUNT_LOG_LEVEL", DEFAULT_LOG_LEVEL).strip() or DEFAULT_LOG_LEVEL,
            mcp_transport=mcp_transport,
            mcp_host=values.get("MCP_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST,
            mcp_port=mcp_port,
        )
