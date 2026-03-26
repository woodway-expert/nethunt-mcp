from __future__ import annotations

import base64

import pytest

from nethunt_mcp.config import Settings
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
