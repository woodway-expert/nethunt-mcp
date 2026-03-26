from __future__ import annotations

import httpx
import pytest
import respx

from nethunt_mcp.automation_client import NetHuntAutomationClient
from nethunt_mcp.client import NetHuntClient
from nethunt_mcp.config import Settings
from nethunt_mcp.errors import NethuntMCPError


def make_settings() -> Settings:
    return Settings.from_env(
        {
            "NETHUNT_EMAIL": "crm@example.com",
            "NETHUNT_API_KEY": "secret",
        }
    )


@pytest.mark.asyncio
async def test_client_includes_basic_auth_header() -> None:
    client = NetHuntClient(make_settings(), retry_backoff_seconds=0)

    assert client.default_headers["Authorization"].startswith("Basic ")

    await client.close()


@pytest.mark.asyncio
async def test_client_retries_retryable_gets() -> None:
    settings = make_settings()
    route_url = f"{settings.api_base_url}/triggers/readable-folder"
    with respx.mock(assert_all_called=True) as router:
        route = router.get(route_url).mock(
            side_effect=[
                httpx.Response(429, json={"error": "slow down"}),
                httpx.Response(200, json=[{"id": "folder-1", "name": "Deals"}]),
            ]
        )
        client = NetHuntClient(settings, retry_backoff_seconds=0)
        result = await client.get_json("/triggers/readable-folder", retryable=True)
        await client.close()

    assert route.call_count == 2
    assert result == [{"id": "folder-1", "name": "Deals"}]


@pytest.mark.asyncio
async def test_client_does_not_retry_non_retryable_post() -> None:
    settings = make_settings()
    route_url = f"{settings.api_base_url}/actions/create-record/folder-1"
    with respx.mock(assert_all_called=True) as router:
        route = router.post(route_url).mock(return_value=httpx.Response(503, json={"error": "down"}))
        client = NetHuntClient(settings, retry_backoff_seconds=0)
        with pytest.raises(NethuntMCPError) as exc_info:
            await client.post_json("/actions/create-record/folder-1", json_body={"fields": {}}, retryable=False)
        await client.close()

    assert route.call_count == 1
    assert exc_info.value.code == "upstream_error"


@pytest.mark.asyncio
async def test_client_normalizes_network_errors() -> None:
    settings = make_settings()
    route_url = f"{settings.api_base_url}/triggers/auth-test"
    request = httpx.Request("GET", route_url)
    with respx.mock(assert_all_called=True) as router:
        router.get(route_url).mock(side_effect=httpx.ConnectError("boom", request=request))
        client = NetHuntClient(settings, retry_backoff_seconds=0)
        with pytest.raises(NethuntMCPError) as exc_info:
            await client.get_json("/triggers/auth-test", retryable=False)
        await client.close()

    assert exc_info.value.code == "network_error"


@pytest.mark.asyncio
async def test_automation_client_uses_cookie_and_extra_headers() -> None:
    settings = Settings.from_env(
        {
            "NETHUNT_EMAIL": "crm@example.com",
            "NETHUNT_API_KEY": "secret",
            "NETHUNT_AUTOMATION_BASE_URL": "https://app.nethunt.com",
            "NETHUNT_AUTOMATION_COOKIE": "session=abc",
            "NETHUNT_AUTOMATION_EXTRA_HEADERS_JSON": '{"X-CSRF-Token":"csrf"}',
        }
    )
    route_url = "https://app.nethunt.com/api/workflows"
    with respx.mock(assert_all_called=True) as router:
        route = router.get(route_url).mock(return_value=httpx.Response(200, json={"items": []}))
        client = NetHuntAutomationClient(settings, retry_backoff_seconds=0)
        result = await client.request_json("GET", "/api/workflows", retryable=True)
        request = route.calls[0].request
        await client.close()

    assert result == {"items": []}
    assert request.headers["Cookie"] == "session=abc"
    assert request.headers["X-CSRF-Token"] == "csrf"
