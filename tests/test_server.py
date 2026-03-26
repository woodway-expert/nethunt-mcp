from __future__ import annotations

import json

import pytest

from nethunt_mcp.config import Settings
from nethunt_mcp.errors import NethuntMCPError
from nethunt_mcp.server import NetHuntMCPApplication


class FakeService:
    async def auth_test(self):
        raise NethuntMCPError(code="auth_error", message="Bad creds", details={"status_code": 401})

    async def list_readable_folders(self, refresh: bool = False):
        return [{"id": "folder-1", "name": "Deals"}]

    async def list_writable_folders(self, refresh: bool = False):
        return []

    async def list_folder_fields(self, folder_id: str, refresh: bool = False):
        return [{"name": "Name"}]

    async def get_record(self, folder_id: str, record_id: str):
        return {"recordId": record_id}

    async def search_records(self, folder_id: str, *, query=None, record_id=None, limit=10):
        return []

    async def list_new_records(self, folder_id: str, *, since=None, limit=None):
        return []

    async def list_updated_records(self, folder_id: str, *, field_names=None, since=None, limit=None):
        return []

    async def list_record_changes(self, folder_id: str, *, record_id=None, field_names=None, since=None, limit=None):
        return []

    async def create_record(self, folder_id: str, *, fields, time_zone=None):
        return {"recordId": "record-1"}

    async def update_record(self, record_id: str, *, set_fields=None, add_fields=None, remove_fields=None, overwrite_default=False):
        return {"recordId": record_id}

    async def create_record_comment(self, record_id: str, *, text: str):
        return {"commentId": "comment-1"}

    async def create_call_log(self, record_id: str, *, text: str, time=None, duration=None):
        return {"callLogId": "call-1"}

    async def delete_record(self, folder_id: str, record_id: str, *, confirm=False, preview_only=False):
        return {"preview": {"recordId": record_id}, "deleted": confirm}

    async def raw_get(self, operation: str, params=None):
        return {"operation": operation}

    async def raw_post(self, operation: str, body=None, *, confirm_write=False):
        return {"operation": operation, "executed": confirm_write}


def make_settings() -> Settings:
    return Settings.from_env({"NETHUNT_EMAIL": "crm@example.com", "NETHUNT_API_KEY": "secret"})


@pytest.mark.asyncio
async def test_server_wraps_errors_in_json_contract() -> None:
    app = NetHuntMCPApplication(FakeService(), make_settings())

    payload = await app.auth_test()

    assert payload["ok"] is False
    assert payload["error"]["code"] == "auth_error"


@pytest.mark.asyncio
async def test_resource_returns_json_text_contract() -> None:
    app = NetHuntMCPApplication(FakeService(), make_settings())

    payload = await app.readable_folders_resource()
    parsed = json.loads(payload)

    assert parsed["ok"] is True
    assert parsed["data"][0]["id"] == "folder-1"
