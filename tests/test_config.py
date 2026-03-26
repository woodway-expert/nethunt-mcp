from __future__ import annotations

import base64
import json

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
