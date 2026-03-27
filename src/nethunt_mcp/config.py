from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping

from dotenv import find_dotenv, load_dotenv

from .errors import ConfigError

DEFAULT_BASE_URL = "https://nethunt.com"
DEFAULT_TIMEZONE = "Europe/Kiev"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_TRANSPORT = "stdio"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18044
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_OPENAI_MODEL = "gpt-5.4"
DEFAULT_TELEGRAM_MCP_URL = "http://127.0.0.1:18044/mcp"
SUPPORTED_TRANSPORTS = {"stdio", "streamable-http"}
_ENV_LOADED = False


def load_runtime_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    env_path = find_dotenv(filename=".env", usecwd=True)
    if env_path:
        load_dotenv(env_path, override=False)
    _ENV_LOADED = True


@dataclass(slots=True, frozen=True)
class Settings:
    nethunt_email: str
    nethunt_api_key: str = field(repr=False)
    nethunt_base_url: str = DEFAULT_BASE_URL
    nethunt_automation_base_url: str = DEFAULT_BASE_URL
    nethunt_automation_cookie: str = field(default="", repr=False)
    nethunt_automation_extra_headers: dict[str, str] = field(default_factory=dict, repr=False)
    nethunt_automation_manifest: dict[str, Any] = field(default_factory=dict, repr=False)
    nethunt_timezone: str = DEFAULT_TIMEZONE
    nethunt_log_level: str = DEFAULT_LOG_LEVEL
    mcp_transport: str = DEFAULT_TRANSPORT
    mcp_host: str = DEFAULT_HOST
    mcp_port: int = DEFAULT_PORT
    mcp_api_key: str = field(default="", repr=False)
    mcp_server_url: str = ""
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @property
    def api_base_url(self) -> str:
        return f"{self.nethunt_base_url.rstrip('/')}/api/v1/zapier"

    @property
    def automation_configured(self) -> bool:
        return bool(self.nethunt_automation_cookie and self.nethunt_automation_manifest)

    @property
    def auth_configured(self) -> bool:
        return bool(self.mcp_api_key) and self.mcp_transport == "streamable-http"

    @property
    def basic_auth_header_value(self) -> str:
        token = f"{self.nethunt_email}:{self.nethunt_api_key}".encode("utf-8")
        return f"Basic {base64.b64encode(token).decode('ascii')}"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        if env is None:
            load_runtime_env()
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

        nethunt_automation_base_url = values.get("NETHUNT_AUTOMATION_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
        if not nethunt_automation_base_url.startswith(("http://", "https://")):
            raise ConfigError(
                code="config_error",
                message="NETHUNT_AUTOMATION_BASE_URL must start with http:// or https://.",
                details={"value": nethunt_automation_base_url},
            )

        mcp_host = values.get("MCP_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
        mcp_api_key = values.get("MCP_API_KEY", "").strip()
        mcp_server_url = values.get("MCP_SERVER_URL", "").strip()
        if mcp_server_url and not mcp_server_url.startswith(("http://", "https://")):
            raise ConfigError(
                code="config_error",
                message="MCP_SERVER_URL must start with http:// or https://.",
                details={"value": mcp_server_url},
            )
        if mcp_api_key and not mcp_server_url:
            mcp_server_url = f"http://{mcp_host}:{mcp_port}"

        return cls(
            nethunt_email=email,
            nethunt_api_key=api_key,
            nethunt_base_url=nethunt_base_url.rstrip("/"),
            nethunt_automation_base_url=nethunt_automation_base_url.rstrip("/"),
            nethunt_automation_cookie=values.get("NETHUNT_AUTOMATION_COOKIE", "").strip(),
            nethunt_automation_extra_headers=_load_json_object(
                values.get("NETHUNT_AUTOMATION_EXTRA_HEADERS_JSON"),
                "NETHUNT_AUTOMATION_EXTRA_HEADERS_JSON",
            ),
            nethunt_automation_manifest=_load_json_object(
                values.get("NETHUNT_AUTOMATION_MANIFEST_JSON"),
                "NETHUNT_AUTOMATION_MANIFEST_JSON",
            ),
            nethunt_timezone=values.get("NETHUNT_TIMEZONE", DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE,
            nethunt_log_level=values.get("NETHUNT_LOG_LEVEL", DEFAULT_LOG_LEVEL).strip() or DEFAULT_LOG_LEVEL,
            mcp_transport=mcp_transport,
            mcp_host=mcp_host,
            mcp_port=mcp_port,
            mcp_api_key=mcp_api_key,
            mcp_server_url=mcp_server_url,
        )


@dataclass(slots=True, frozen=True)
class TelegramBotSettings:
    telegram_bot_token: str = field(repr=False)
    telegram_allowed_user_ids: frozenset[int]
    openai_api_key: str = field(repr=False)
    openai_model: str = DEFAULT_OPENAI_MODEL
    telegram_mcp_url: str = DEFAULT_TELEGRAM_MCP_URL
    telegram_mcp_api_key: str = field(default="", repr=False)

    @property
    def mcp_auth_headers(self) -> dict[str, str]:
        if not self.telegram_mcp_api_key:
            return {}
        return {"Authorization": f"Bearer {self.telegram_mcp_api_key}"}

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "TelegramBotSettings":
        if env is None:
            load_runtime_env()
        values = env or os.environ

        bot_token = values.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not bot_token:
            raise ConfigError(code="config_error", message="TELEGRAM_BOT_TOKEN is required.")

        allowed_user_ids = _parse_allowed_user_ids(values.get("TELEGRAM_ALLOWED_USER_IDS", ""))
        if not allowed_user_ids:
            raise ConfigError(code="config_error", message="TELEGRAM_ALLOWED_USER_IDS is required.")

        openai_api_key = values.get("OPENAI_API_KEY", "").strip()
        if not openai_api_key:
            raise ConfigError(code="config_error", message="OPENAI_API_KEY is required.")

        openai_model = values.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL
        telegram_mcp_url = values.get("TELEGRAM_MCP_URL", DEFAULT_TELEGRAM_MCP_URL).strip() or DEFAULT_TELEGRAM_MCP_URL
        if not telegram_mcp_url.startswith(("http://", "https://")):
            raise ConfigError(
                code="config_error",
                message="TELEGRAM_MCP_URL must start with http:// or https://.",
                details={"value": telegram_mcp_url},
            )

        telegram_mcp_api_key = values.get("TELEGRAM_MCP_API_KEY", "").strip() or values.get("MCP_API_KEY", "").strip()

        return cls(
            telegram_bot_token=bot_token,
            telegram_allowed_user_ids=frozenset(allowed_user_ids),
            openai_api_key=openai_api_key,
            openai_model=openai_model,
            telegram_mcp_url=telegram_mcp_url,
            telegram_mcp_api_key=telegram_mcp_api_key,
        )


def _load_json_object(raw: str | None, env_name: str) -> dict[str, Any]:
    value = (raw or "").strip()
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            code="config_error",
            message=f"{env_name} must be valid JSON.",
            details={"value": value[:200]},
        ) from exc
    if not isinstance(parsed, dict):
        raise ConfigError(
            code="config_error",
            message=f"{env_name} must decode to a JSON object.",
        )
    if env_name == "NETHUNT_AUTOMATION_EXTRA_HEADERS_JSON":
        normalized_headers: dict[str, str] = {}
        for key, value in parsed.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ConfigError(
                    code="config_error",
                    message=f"{env_name} must contain only string keys and values.",
                )
            normalized_headers[key] = value
        return normalized_headers
    return parsed


def _parse_allowed_user_ids(raw: str) -> set[int]:
    parsed_ids: set[int] = set()
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        try:
            user_id = int(value)
        except ValueError as exc:
            raise ConfigError(
                code="config_error",
                message="TELEGRAM_ALLOWED_USER_IDS must contain only integers.",
                details={"value": value},
            ) from exc
        if user_id <= 0:
            raise ConfigError(
                code="config_error",
                message="TELEGRAM_ALLOWED_USER_IDS must contain only positive integers.",
                details={"value": value},
            )
        parsed_ids.add(user_id)
    return parsed_ids
