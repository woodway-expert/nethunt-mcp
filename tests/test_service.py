from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from nethunt_mcp.config import Settings
from nethunt_mcp.errors import ValidationError
from nethunt_mcp.service import NetHuntService


@dataclass
class FakeClient:
    get_responses: dict[str, Any] = field(default_factory=dict)
    post_responses: dict[str, Any] = field(default_factory=dict)
    get_calls: list[tuple[str, Any, bool]] = field(default_factory=list)
    post_calls: list[tuple[str, Any, Any, bool]] = field(default_factory=list)

    async def get_json(self, path: str, *, query: Any = None, retryable: bool = True) -> Any:
        self.get_calls.append((path, query, retryable))
        return self.get_responses[path]

    async def post_json(
        self,
        path: str,
        *,
        query: Any = None,
        json_body: Any = None,
        retryable: bool = False,
    ) -> Any:
        self.post_calls.append((path, query, json_body, retryable))
        return self.post_responses.get(path, {})

    async def close(self) -> None:
        return None


def make_settings() -> Settings:
    return Settings.from_env(
        {
            "NETHUNT_EMAIL": "crm@example.com",
            "NETHUNT_API_KEY": "secret",
        }
    )


@pytest.mark.asyncio
async def test_discovery_cache_uses_cached_values_until_refresh() -> None:
    client = FakeClient(
        get_responses={
            "/triggers/readable-folder": [{"id": "folder-1", "name": "Deals"}],
        }
    )
    service = NetHuntService(client, make_settings())

    first = await service.list_readable_folders()
    second = await service.list_readable_folders()
    third = await service.list_readable_folders(refresh=True)

    assert first == second == third
    assert client.get_calls == [
        ("/triggers/readable-folder", None, True),
        ("/triggers/readable-folder", None, True),
    ]


@pytest.mark.asyncio
async def test_update_record_builds_field_actions_payload() -> None:
    client = FakeClient(post_responses={"/actions/update-record/record-1": {"recordId": "record-1"}})
    service = NetHuntService(client, make_settings())

    result = await service.update_record(
        "record-1",
        set_fields={"Name": "Ada"},
        add_fields={"Tags": ["MCP"]},
        remove_fields={"Country": "GB"},
        overwrite_default=False,
    )

    assert result == {"recordId": "record-1"}
    assert client.post_calls == [
        (
            "/actions/update-record/record-1",
            {"overwrite": "false"},
            {
                "fieldActions": {
                    "Name": {"overwrite": True, "add": "Ada"},
                    "Tags": {"add": ["MCP"]},
                    "Country": {"remove": "GB"},
                }
            },
            False,
        )
    ]


@pytest.mark.asyncio
async def test_delete_record_returns_preview_without_confirm() -> None:
    client = FakeClient(
        get_responses={
            "/searches/find-record/folder-1": [{"recordId": "record-1", "fields": {"Name": "Ada"}}],
        }
    )
    service = NetHuntService(client, make_settings())

    result = await service.delete_record("folder-1", "record-1", confirm=False, preview_only=True)

    assert result["deleted"] is False
    assert result["preview"]["record"]["recordId"] == "record-1"
    assert client.post_calls == []


@pytest.mark.asyncio
async def test_raw_post_requires_explicit_confirmation_to_execute() -> None:
    client = FakeClient(post_responses={"/actions/create-record/folder-1": {"recordId": "record-1"}})
    service = NetHuntService(client, make_settings())

    preview = await service.raw_post(
        "create_record",
        body={"folder_id": "folder-1", "timeZone": "Europe/Kiev", "fields": {"Name": "Ada"}},
        confirm_write=False,
    )
    executed = await service.raw_post(
        "create_record",
        body={"folder_id": "folder-1", "timeZone": "Europe/Kiev", "fields": {"Name": "Ada"}},
        confirm_write=True,
    )

    assert preview["executed"] is False
    assert preview["preview"]["path"] == "/actions/create-record/folder-1"
    assert executed["executed"] is True
    assert client.post_calls[0][0] == "/actions/create-record/folder-1"


@pytest.mark.asyncio
async def test_raw_get_rejects_unknown_operation() -> None:
    service = NetHuntService(FakeClient(), make_settings())

    with pytest.raises(ValidationError):
        await service.raw_get("unknown_operation")


@pytest.mark.asyncio
async def test_update_record_rejects_overlapping_field_inputs() -> None:
    service = NetHuntService(FakeClient(), make_settings())

    with pytest.raises(ValidationError):
        await service.update_record(
            "record-1",
            set_fields={"Name": "Ada"},
            add_fields={"Name": "Grace"},
        )
