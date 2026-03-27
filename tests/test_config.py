from __future__ import annotations

import base64
import json

import pytest

from nethunt_mcp.config import Settings, TelegramBotSettings
from nethunt_mcp.errors import ConfigError


def test_settings_from_env_reads_required_fields() -> None:
    settings = Settings.from_env(
        {
            "NETHUNT_EMAIL": "crm@example.com",
            "NETHUNT_API_KEY": "secret",
            "MCP_TRANSPORT": "streamable-http",
            "MCP_HOST": "0.0.0.0",
            "MCP_PORT": "9000",
        }
    )

    assert settings.api_base_url == "https://nethunt.com/api/v1/zapier"
    assert settings.mcp_transport == "streamable-http"
    assert settings.mcp_host == "0.0.0.0"
    assert settings.mcp_port == 9000


def test_settings_builds_basic_auth_header() -> None:
    settings = Settings.from_env(
        {
            "NETHUNT_EMAIL": "crm@example.com",
            "NETHUNT_API_KEY": "secret",
        }
    )

    expected = base64.b64encode(b"crm@example.com:secret").decode("ascii")
    assert settings.basic_auth_header_value == f"Basic {expected}"


def test_settings_require_email() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({"NETHUNT_API_KEY": "secret"})


def test_settings_reject_invalid_transport() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env(
            {
                "NETHUNT_EMAIL": "crm@example.com",
                "NETHUNT_API_KEY": "secret",
                "MCP_TRANSPORT": "sse",
            }
        )


def test_settings_parse_automation_options() -> None:
    settings = Settings.from_env(
        {
            "NETHUNT_EMAIL": "crm@example.com",
            "NETHUNT_API_KEY": "secret",
            "NETHUNT_AUTOMATION_BASE_URL": "https://app.nethunt.com",
            "NETHUNT_AUTOMATION_COOKIE": "session=abc",
            "NETHUNT_AUTOMATION_EXTRA_HEADERS_JSON": json.dumps({"X-CSRF-Token": "csrf"}),
            "NETHUNT_AUTOMATION_MANIFEST_JSON": json.dumps(
                {
                    "workflow": {
                        "operations": {
                            "list": {"method": "GET", "path": "/api/workflows"},
                            "get": {"method": "GET", "path": "/api/workflows/{automation_id}"},
                            "create": {"method": "POST", "path": "/api/workflows"},
                            "update": {"method": "PUT", "path": "/api/workflows/{automation_id}"},
                            "delete": {"method": "DELETE", "path": "/api/workflows/{automation_id}"},
                            "set_enabled": {"method": "PATCH", "path": "/api/workflows/{automation_id}/state"},
                        },
                        "editor_operations": {
                            "rename": {"method": "POST", "path": "/api/command"},
                        },
                    }
                }
            ),
        }
    )

    assert settings.nethunt_automation_base_url == "https://app.nethunt.com"
    assert settings.nethunt_automation_cookie == "session=abc"
    assert settings.nethunt_automation_extra_headers == {"X-CSRF-Token": "csrf"}
    assert "workflow" in settings.nethunt_automation_manifest
    assert "rename" in settings.nethunt_automation_manifest["workflow"]["editor_operations"]
    assert settings.automation_configured is True


def test_settings_reject_non_string_automation_headers() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env(
            {
                "NETHUNT_EMAIL": "crm@example.com",
                "NETHUNT_API_KEY": "secret",
                "NETHUNT_AUTOMATION_EXTRA_HEADERS_JSON": json.dumps({"X-CSRF-Token": 123}),
            }
        )


def test_settings_parse_mcp_api_key() -> None:
    settings_http = Settings.from_env(
        {
            "NETHUNT_EMAIL": "crm@example.com",
            "NETHUNT_API_KEY": "secret",
            "MCP_TRANSPORT": "streamable-http",
            "MCP_API_KEY": "my-bearer-token",
            "MCP_SERVER_URL": "https://mcp.example.com",
        }
    )

    assert settings_http.mcp_api_key == "my-bearer-token"
    assert settings_http.mcp_server_url == "https://mcp.example.com"
    assert settings_http.auth_configured is True

    settings_stdio = Settings.from_env(
        {
            "NETHUNT_EMAIL": "crm@example.com",
            "NETHUNT_API_KEY": "secret",
            "MCP_API_KEY": "my-bearer-token",
        }
    )

    assert settings_stdio.auth_configured is False


def test_settings_mcp_api_key_auto_derives_server_url() -> None:
    settings = Settings.from_env(
        {
            "NETHUNT_EMAIL": "crm@example.com",
            "NETHUNT_API_KEY": "secret",
            "MCP_TRANSPORT": "streamable-http",
            "MCP_HOST": "127.0.0.1",
            "MCP_PORT": "18044",
            "MCP_API_KEY": "my-bearer-token",
        }
    )

    assert settings.mcp_server_url == "http://127.0.0.1:18044"


def test_settings_rejects_invalid_server_url() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env(
            {
                "NETHUNT_EMAIL": "crm@example.com",
                "NETHUNT_API_KEY": "secret",
                "MCP_SERVER_URL": "not-a-url",
            }
        )


def test_telegram_bot_settings_read_required_fields() -> None:
    settings = TelegramBotSettings.from_env(
        {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_ALLOWED_USER_IDS": "123, 456",
            "OPENAI_API_KEY": "openai-secret",
            "OPENAI_MODEL": "gpt-5.4",
            "TELEGRAM_MCP_URL": "https://mcp.example.com/mcp",
            "TELEGRAM_MCP_API_KEY": "mcp-secret",
        }
    )

    assert settings.telegram_allowed_user_ids == frozenset({123, 456})
    assert settings.openai_model == "gpt-5.4"
    assert settings.telegram_mcp_url == "https://mcp.example.com/mcp"
    assert settings.mcp_auth_headers == {"Authorization": "Bearer mcp-secret"}


def test_telegram_bot_settings_require_allowed_user_ids() -> None:
    with pytest.raises(ConfigError):
        TelegramBotSettings.from_env(
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "OPENAI_API_KEY": "openai-secret",
            }
        )


def test_telegram_bot_settings_reject_invalid_allowed_user_ids() -> None:
    with pytest.raises(ConfigError):
        TelegramBotSettings.from_env(
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_USER_IDS": "123, not-a-number",
                "OPENAI_API_KEY": "openai-secret",
            }
        )


def test_telegram_bot_settings_reject_invalid_mcp_url() -> None:
    with pytest.raises(ConfigError):
        TelegramBotSettings.from_env(
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_USER_IDS": "123",
                "OPENAI_API_KEY": "openai-secret",
                "TELEGRAM_MCP_URL": "localhost:18044/mcp",
            }
        )


def test_telegram_bot_settings_fall_back_to_mcp_api_key() -> None:
    settings = TelegramBotSettings.from_env(
        {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_ALLOWED_USER_IDS": "123",
            "OPENAI_API_KEY": "openai-secret",
            "MCP_API_KEY": "shared-secret",
        }
    )

    assert settings.telegram_mcp_api_key == "shared-secret"
