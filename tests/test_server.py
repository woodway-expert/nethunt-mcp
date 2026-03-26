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
        return [{"name": "Name", "fieldId": "41", "fieldType": "TEXT", "metadataSource": {"fieldId": "raw"}}]

    async def list_automation_field_references(self, folder_id: str, *, kind=None):
        return [
            {
                "folderId": folder_id,
                "fieldId": "41",
                "referenceCount": 1,
                "metadataSource": {"fieldId": "automation_imports"},
            }
        ]

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

    async def list_automation_kinds(self):
        return [
            {
                "kind": "workflow",
                "operations": ["list", "get", "create", "update", "delete", "set_enabled"],
                "editorOperations": ["activate", "rename"],
            }
        ]

    async def list_automations(self, *, kind=None):
        return [{"kind": kind or "workflow", "automationId": "wf-1"}]

    async def get_automation(self, kind: str, automation_id: str, *, include_branches=False):
        payload = {"kind": kind, "automationId": automation_id}
        if include_branches:
            payload["branches"] = [{"branchId": "1", "branchNum": 1, "steps": [{"stepId": "1", "stepNum": 1, "type": "RECORD_CREATED"}]}]
            payload["branchGraph"] = {"branchCount": 1, "stepCount": 1}
        return payload

    async def create_automation(self, kind: str, payload, *, confirm_write=False):
        if not confirm_write:
            return {"preview": {"kind": kind, "json": payload}, "executed": False}
        return {"executed": True, "result": {"kind": kind, "automationId": "wf-1"}}

    async def update_automation(self, kind: str, automation_id: str, payload, *, confirm_write=False):
        if not confirm_write:
            return {"preview": {"kind": kind, "automationId": automation_id, "json": payload}, "executed": False}
        return {"executed": True, "result": {"kind": kind, "automationId": automation_id}}

    async def delete_automation(self, kind: str, automation_id: str, *, confirm=False, preview_only=False):
        return {"preview": {"kind": kind, "automationId": automation_id}, "deleted": confirm}

    async def set_automation_enabled(self, kind: str, automation_id: str, enabled: bool, *, confirm_write=False):
        if not confirm_write:
            return {
                "preview": {"kind": kind, "automationId": automation_id, "enabled": enabled},
                "executed": False,
            }
        return {"executed": True, "result": {"kind": kind, "automationId": automation_id, "enabled": enabled}}

    async def activate_automation(self, kind: str, automation_id: str, *, confirm_write=False):
        if not confirm_write:
            return {"preview": {"kind": kind, "automationId": automation_id}, "executed": False}
        return {"executed": True, "result": {"kind": kind, "automationId": automation_id, "enabled": True}}

    async def deactivate_automation(self, kind: str, automation_id: str, *, confirm_write=False):
        if not confirm_write:
            return {"preview": {"kind": kind, "automationId": automation_id}, "executed": False}
        return {"executed": True, "result": {"kind": kind, "automationId": automation_id, "enabled": False}}

    async def rename_automation(self, kind: str, automation_id: str, name: str, *, confirm_write=False):
        if not confirm_write:
            return {"preview": {"kind": kind, "automationId": automation_id, "name": name}, "executed": False}
        return {"executed": True, "result": {"kind": kind, "automationId": automation_id, "name": name}}

    async def get_automation_step_details(self, kind: str, automation_id: str, step_num: int, *, list_options=None):
        return {
            "kind": kind,
            "automationId": automation_id,
            "stepNum": step_num,
            "stepId": "step-2",
            "branchId": "1",
            "listOptions": list_options,
        }

    async def add_automation_step(
        self,
        kind: str,
        automation_id: str,
        step_type: str,
        payload,
        *,
        branch_id,
        role,
        confirm_write=False,
    ):
        if not confirm_write:
            return {
                "preview": {
                    "kind": kind,
                    "automationId": automation_id,
                    "stepType": step_type,
                    "payload": payload,
                    "branchId": branch_id,
                    "role": role,
                },
                "executed": False,
            }
        return {
            "executed": True,
            "result": {
                "kind": kind,
                "automationId": automation_id,
                "stepType": step_type,
                "branchId": branch_id,
                "role": role,
            },
        }

    async def update_automation_step(
        self,
        kind: str,
        automation_id: str,
        step_num: int,
        payload,
        *,
        branch_id,
        step_id=None,
        confirm_write=False,
    ):
        if not confirm_write:
            return {
                "preview": {
                    "kind": kind,
                    "automationId": automation_id,
                    "stepNum": step_num,
                    "payload": payload,
                    "branchId": branch_id,
                    "stepId": step_id,
                },
                "executed": False,
            }
        return {
            "executed": True,
            "result": {
                "kind": kind,
                "automationId": automation_id,
                "stepNum": step_num,
                "branchId": branch_id,
                "stepId": step_id,
            },
        }

    async def delete_automation_step(
        self,
        kind: str,
        automation_id: str,
        step_num: int,
        *,
        child_branch_num=None,
        payload=None,
        confirm_write=False,
    ):
        if not confirm_write:
            return {
                "preview": {
                    "kind": kind,
                    "automationId": automation_id,
                    "stepNum": step_num,
                    "childBranchNum": child_branch_num,
                    "payload": payload,
                },
                "executed": False,
            }
        return {
            "executed": True,
            "result": {
                "kind": kind,
                "automationId": automation_id,
                "stepNum": step_num,
                "childBranchNum": child_branch_num,
            },
        }

    async def add_automation_split(self, kind: str, automation_id: str, step_num: int, payload=None, *, confirm_write=False):
        if not confirm_write:
            return {
                "preview": {"kind": kind, "automationId": automation_id, "stepNum": step_num, "payload": payload},
                "executed": False,
            }
        return {"executed": True, "result": {"kind": kind, "automationId": automation_id, "stepNum": step_num}}


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


@pytest.mark.asyncio
async def test_raw_get_wraps_response_without_operation_meta_collision() -> None:
    app = NetHuntMCPApplication(FakeService(), make_settings())

    payload = await app.raw_get("list_folder_fields", {"folder_id": "folder-1"})

    assert payload["ok"] is True
    assert payload["data"]["operation"] == "list_folder_fields"
    assert payload["meta"]["raw_operation"] == "list_folder_fields"


@pytest.mark.asyncio
async def test_create_automation_requires_confirmation() -> None:
    app = NetHuntMCPApplication(FakeService(), make_settings())

    payload = await app.create_automation("workflow", {"name": "Welcome"}, confirm_write=False)

    assert payload["ok"] is False
    assert payload["error"]["code"] == "confirmation_required"


@pytest.mark.asyncio
async def test_get_automation_can_include_branches() -> None:
    app = NetHuntMCPApplication(FakeService(), make_settings())

    payload = await app.get_automation("workflow", "wf-1", include_branches=True)

    assert payload["ok"] is True
    assert payload["data"]["branches"][0]["steps"][0]["type"] == "RECORD_CREATED"
    assert payload["data"]["branches"][0]["branchId"] == "1"
    assert payload["data"]["branchGraph"]["stepCount"] == 1


@pytest.mark.asyncio
async def test_activate_automation_requires_confirmation() -> None:
    app = NetHuntMCPApplication(FakeService(), make_settings())

    payload = await app.activate_automation("workflow", "wf-1", confirm_write=False)

    assert payload["ok"] is False
    assert payload["error"]["code"] == "confirmation_required"


@pytest.mark.asyncio
async def test_get_automation_step_details_wraps_response_contract() -> None:
    app = NetHuntMCPApplication(FakeService(), make_settings())

    payload = await app.get_automation_step_details("workflow", "wf-1", 2, {"limit": 25})

    assert payload["ok"] is True
    assert payload["data"]["stepNum"] == 2
    assert payload["data"]["stepId"] == "step-2"
    assert payload["data"]["branchId"] == "1"
    assert payload["data"]["listOptions"] == {"limit": 25}


@pytest.mark.asyncio
async def test_list_automation_field_references_wraps_response_contract() -> None:
    app = NetHuntMCPApplication(FakeService(), make_settings())

    payload = await app.list_automation_field_references("folder-1", kind="workflow")

    assert payload["ok"] is True
    assert payload["data"][0]["fieldId"] == "41"
    assert payload["data"][0]["metadataSource"]["fieldId"] == "automation_imports"
    assert payload["meta"]["folder_id"] == "folder-1"


@pytest.mark.asyncio
async def test_add_automation_step_requires_confirmation_with_branch_and_role() -> None:
    app = NetHuntMCPApplication(FakeService(), make_settings())

    payload = await app.add_automation_step(
        "workflow",
        "wf-1",
        "CREATE_TASK",
        {"folderId": "folder-1"},
        1,
        "ACTION",
        confirm_write=False,
    )

    assert payload["ok"] is False
    assert payload["error"]["code"] == "confirmation_required"
    assert payload["error"]["details"]["preview"]["branchId"] == 1
    assert payload["error"]["details"]["preview"]["role"] == "ACTION"


@pytest.mark.asyncio
async def test_update_automation_step_requires_confirmation_with_branch_id() -> None:
    app = NetHuntMCPApplication(FakeService(), make_settings())

    payload = await app.update_automation_step(
        "workflow",
        "wf-1",
        3,
        {"unit": "DAYS", "amount": 3},
        1,
        confirm_write=False,
    )

    assert payload["ok"] is False
    assert payload["error"]["code"] == "confirmation_required"
    assert payload["error"]["details"]["preview"]["branchId"] == 1
    assert payload["error"]["details"]["preview"]["stepId"] is None


@pytest.mark.asyncio
async def test_automation_capabilities_resource_returns_json_text_contract() -> None:
    app = NetHuntMCPApplication(FakeService(), make_settings())

    payload = await app.automation_capabilities_resource()
    parsed = json.loads(payload)

    assert parsed["ok"] is True
    assert parsed["data"][0]["kind"] == "workflow"
    assert parsed["data"][0]["editorOperations"] == ["activate", "rename"]


def test_tool_descriptions_include_model_facing_guidance() -> None:
    app = NetHuntMCPApplication(FakeService(), make_settings())

    tool = app.server._tool_manager.get_tool("add_automation_step")

    assert tool.description == "Add a step to an automation branch through the NetHunt editor RPC wrapper. Requires confirmation."
    assert tool.parameters["properties"]["kind"]["description"].startswith("Configured automation kind")
    assert tool.parameters["properties"]["payload"]["description"] == "NetHunt editor payload for the new automation step."
    assert tool.parameters["properties"]["branch_id"]["description"] == "Target branch identifier required by NetHunt editor RPC calls."
    assert tool.parameters["properties"]["confirm_write"]["description"] == "Explicit confirmation flag required for mutating write operations."


@pytest.mark.asyncio
async def test_resource_descriptions_are_registered() -> None:
    app = NetHuntMCPApplication(FakeService(), make_settings())

    resource = await app.server._resource_manager.get_resource("nethunt://folders/readable")

    assert resource.description == "JSON snapshot of the readable folder catalog, equivalent to `list_readable_folders(refresh=false)`."
