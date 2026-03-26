from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

import pytest

from nethunt_mcp.config import Settings
from nethunt_mcp.errors import ConfigError, NethuntMCPError, ValidationError
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


@dataclass
class FakeAutomationClient:
    responses: dict[tuple[str, str], Any] = field(default_factory=dict)
    calls: list[tuple[str, str, Any, Any, bool]] = field(default_factory=list)

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        query: Any = None,
        json_body: Any = None,
        retryable: bool = False,
    ) -> Any:
        self.calls.append((method, path, query, json_body, retryable))
        return self.responses[(method, path)]

    async def close(self) -> None:
        return None


def make_settings() -> Settings:
    return Settings.from_env(
        {
            "NETHUNT_EMAIL": "crm@example.com",
            "NETHUNT_API_KEY": "secret",
        }
    )


def make_automation_settings() -> Settings:
    return Settings.from_env(
        {
            "NETHUNT_EMAIL": "crm@example.com",
            "NETHUNT_API_KEY": "secret",
            "NETHUNT_AUTOMATION_COOKIE": "session=abc",
            "NETHUNT_AUTOMATION_MANIFEST_JSON": json.dumps(
                {
                    "workflow": {
                        "label": "Workflows",
                        "name_path": "attributes.name",
                        "enabled_path": "attributes.enabled",
                        "samples": {
                            "create": {"attributes": {"name": "Welcome", "enabled": True}},
                            "update": {"attributes": {"name": "Welcome 2", "enabled": False}},
                        },
                        "operations": {
                            "list": {
                                "method": "GET",
                                "path": "/api/workflows",
                                "response_path": "items",
                            },
                            "get": {
                                "method": "GET",
                                "path": "/api/workflows/{automation_id}",
                                "response_path": "item",
                            },
                            "create": {
                                "method": "POST",
                                "path": "/api/workflows",
                                "json": "$payload",
                                "response_path": "item",
                            },
                            "update": {
                                "method": "PUT",
                                "path": "/api/workflows/{automation_id}",
                                "json": "$payload",
                                "response_path": "item",
                            },
                            "delete": {
                                "method": "DELETE",
                                "path": "/api/workflows/{automation_id}",
                            },
                            "set_enabled": {
                                "method": "PATCH",
                                "path": "/api/workflows/{automation_id}/state",
                                "json": {"enabled": "$enabled"},
                                "response_path": "item",
                            },
                        },
                        "editor_operations": {
                            "activate": {
                                "method": "POST",
                                "path": "/api/command",
                                "json": {
                                    "service": "automation",
                                    "name": "activateAutomation",
                                    "data": {
                                        "workspaceId": "6911d891768a235848ac5535",
                                        "automationId": "{automation_id}",
                                    },
                                },
                            },
                            "deactivate": {
                                "method": "POST",
                                "path": "/api/command",
                                "json": {
                                    "service": "automation",
                                    "name": "deactivateAutomation",
                                    "data": {
                                        "workspaceId": "6911d891768a235848ac5535",
                                        "automationId": "{automation_id}",
                                    },
                                },
                            },
                            "rename": {
                                "method": "POST",
                                "path": "/api/command",
                                "json": {
                                    "service": "automation",
                                    "name": "updateAutomationName",
                                    "data": {
                                        "workspaceId": "6911d891768a235848ac5535",
                                        "automationId": "{automation_id}",
                                        "name": "$name",
                                    },
                                },
                            },
                            "get_step_details": {
                                "method": "POST",
                                "path": "/api/commands",
                                "json": [
                                    {
                                        "service": "automation",
                                        "name": "getStepDetails",
                                        "data": {
                                            "workspaceId": "6911d891768a235848ac5535",
                                            "automationId": "{automation_id}",
                                            "stepNum": "$step_num",
                                            "listOptions": "$list_options",
                                        },
                                        "id": "90",
                                    }
                                ],
                                "response_path": "0.result",
                            },
                            "add_step": {
                                "method": "POST",
                                "path": "/api/command",
                                "json": {
                                    "service": "automation",
                                    "name": "addStep",
                                    "data": {
                                        "workspaceId": "6911d891768a235848ac5535",
                                        "automationId": "{automation_id}",
                                        "branchId": "$branch_id",
                                        "role": "$role",
                                        "type": "$step_type",
                                        "options": "$payload",
                                    },
                                },
                            },
                            "update_step": {
                                "method": "POST",
                                "path": "/api/command",
                                "json": {
                                    "service": "automation",
                                    "name": "updateStepOptions",
                                    "data": {
                                        "workspaceId": "6911d891768a235848ac5535",
                                        "automationId": "{automation_id}",
                                        "stepNum": "$step_num",
                                        "branchId": "$branch_id",
                                        "stepId": "$step_id",
                                        "options": "$payload",
                                    },
                                },
                            },
                            "delete_step": {
                                "method": "POST",
                                "path": "/api/command",
                                "json": {
                                    "service": "automation",
                                    "name": "deleteStep",
                                    "data": {
                                        "workspaceId": "6911d891768a235848ac5535",
                                        "automationId": "{automation_id}",
                                        "stepNum": "$step_num",
                                        "childBranchNum": "$child_branch_num",
                                    },
                                },
                            },
                            "add_split": {
                                "method": "POST",
                                "path": "/api/command",
                                "json": {
                                    "service": "automation",
                                    "name": "addSplit",
                                    "data": {
                                        "workspaceId": "6911d891768a235848ac5535",
                                        "automationId": "{automation_id}",
                                        "stepNum": "$step_num",
                                        "options": "$payload",
                                    },
                                },
                            },
                        },
                    },
                    "partial": {
                        "operations": {
                            "list": {"method": "GET", "path": "/api/partial"},
                        }
                    },
                }
            ),
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
async def test_list_folder_fields_enriches_metadata_and_reference_provenance() -> None:
    client = FakeClient(
        get_responses={
            "/triggers/folder-field/folder-1": [
                {
                    "name": "Status",
                    "fieldId": "41",
                    "fieldType": "LIST",
                    "options": [{"id": "open", "label": "Open"}],
                },
                {"name": "Next Contact"},
            ],
        }
    )
    automation_client = FakeAutomationClient(
        responses={
            ("GET", "/api/workflows"): {
                "items": [
                    {
                        "id": "wf-1",
                        "attributes": {"name": "Welcome", "enabled": True},
                        "imports": [{"type": "FIELD", "folderId": "folder-1", "fieldId": "41"}],
                    }
                ]
            }
        }
    )
    service = NetHuntService(client, make_automation_settings(), automation_client=automation_client)

    result = await service.list_folder_fields("folder-1")

    assert result[0]["fieldName"] == "Status"
    assert result[0]["fieldId"] == "41"
    assert result[0]["fieldType"] == "LIST"
    assert result[0]["fieldOptions"] == [
        {
            "id": "open",
            "label": "Open",
            "value": "Open",
            "raw": {"id": "open", "label": "Open"},
        }
    ]
    assert result[0]["referenceCount"] == 1
    assert result[0]["referencedBy"] == [{"kind": "workflow", "automationId": "wf-1", "name": "Welcome"}]
    assert result[0]["metadataSource"] == {
        "fieldName": "raw",
        "fieldId": "raw",
        "fieldType": "raw",
        "fieldOptions": "raw",
    }
    assert result[1]["fieldName"] == "Next Contact"
    assert result[1]["fieldId"] is None
    assert result[1]["referenceCount"] == 0


@pytest.mark.asyncio
async def test_search_records_enriches_field_metadata() -> None:
    client = FakeClient(
        get_responses={
            "/searches/find-record/folder-1": [
                {
                    "recordId": "record-1",
                    "fields": {
                        "Status": "Open",
                        "Next Contact": "2026-03-26",
                    },
                }
            ],
            "/triggers/folder-field/folder-1": [
                {
                    "name": "Status",
                    "fieldId": "41",
                    "fieldType": "LIST",
                    "options": [{"id": "open", "label": "Open"}],
                },
                {"name": "Next Contact", "fieldId": "7", "fieldType": "DATE"},
            ],
        }
    )
    service = NetHuntService(client, make_settings())

    result = await service.search_records("folder-1", query="Ada")

    assert result[0]["folderId"] == "folder-1"
    assert result[0]["fieldIds"] == {"Status": "41", "Next Contact": "7"}
    assert result[0]["fieldMetadata"]["Status"]["fieldType"] == "LIST"
    assert result[0]["fieldMetadata"]["Status"]["fieldOptions"][0]["id"] == "open"
    assert result[0]["fieldMetadata"]["Next Contact"]["fieldType"] == "DATE"
    assert result[0]["fieldNames"] == ["Next Contact", "Status"]


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


@pytest.mark.asyncio
async def test_list_automation_kinds_returns_only_supported_manifest_entries() -> None:
    service = NetHuntService(FakeClient(), make_automation_settings(), automation_client=FakeAutomationClient())

    result = await service.list_automation_kinds()

    assert result == [
        {
            "kind": "workflow",
            "label": "Workflows",
            "operations": ["create", "delete", "get", "list", "set_enabled", "update"],
            "editorOperations": [
                "activate",
                "add_split",
                "add_step",
                "deactivate",
                "delete_step",
                "get_step_details",
                "rename",
                "update_step",
            ],
            "idPath": "id",
            "namePath": "attributes.name",
            "enabledPath": "attributes.enabled",
            "samples": {
                "create": {"attributes": {"name": "Welcome", "enabled": True}},
                "update": {"attributes": {"name": "Welcome 2", "enabled": False}},
            },
        }
    ]


@pytest.mark.asyncio
async def test_list_automations_normalizes_items() -> None:
    automation_client = FakeAutomationClient(
        responses={
            (
                "GET",
                "/api/workflows",
            ): {
                "items": [
                    {"id": "wf-1", "attributes": {"name": "Welcome", "enabled": True}},
                ]
            }
        }
    )
    service = NetHuntService(FakeClient(), make_automation_settings(), automation_client=automation_client)

    result = await service.list_automations(kind="workflow")

    assert result == [
        {
            "kind": "workflow",
            "automationId": "wf-1",
            "name": "Welcome",
            "enabled": True,
            "raw": {"id": "wf-1", "attributes": {"name": "Welcome", "enabled": True}},
            "imports": [],
            "fieldReferences": [],
            "referenceCount": 0,
        }
    ]
    assert automation_client.calls == [("GET", "/api/workflows", None, None, True)]


@pytest.mark.asyncio
async def test_list_automation_field_references_groups_existing_imports() -> None:
    automation_client = FakeAutomationClient(
        responses={
            (
                "GET",
                "/api/workflows",
            ): {
                "items": [
                    {
                        "id": "wf-1",
                        "attributes": {"name": "Welcome", "enabled": True},
                        "imports": [
                            {"type": "FIELD", "folderId": "folder-1", "fieldId": "41"},
                            {"type": "FIELD", "folderId": "folder-1", "fieldId": "7"},
                        ],
                    },
                    {
                        "id": "wf-2",
                        "attributes": {"name": "Reminder", "enabled": False},
                        "imports": [
                            {"type": "FIELD", "folderId": "folder-1", "fieldId": "41"},
                            {"type": "FIELD", "folderId": "folder-2", "fieldId": "3"},
                        ],
                    },
                ]
            }
        }
    )
    service = NetHuntService(FakeClient(), make_automation_settings(), automation_client=automation_client)

    result = await service.list_automation_field_references("folder-1", kind="workflow")

    assert result == [
        {
            "folderId": "folder-1",
            "fieldId": "41",
            "referenceCount": 2,
            "referencedBy": [
                {"kind": "workflow", "automationId": "wf-2", "name": "Reminder"},
                {"kind": "workflow", "automationId": "wf-1", "name": "Welcome"},
            ],
            "referencePaths": ["imports[0]"],
            "fieldName": None,
            "fieldType": None,
            "fieldOptions": None,
            "metadataSource": {
                "fieldId": "automation_imports",
                "fieldName": None,
                "fieldType": None,
                "fieldOptions": None,
            },
        },
        {
            "folderId": "folder-1",
            "fieldId": "7",
            "referenceCount": 1,
            "referencedBy": [
                {"kind": "workflow", "automationId": "wf-1", "name": "Welcome"},
            ],
            "referencePaths": ["imports[1]"],
            "fieldName": None,
            "fieldType": None,
            "fieldOptions": None,
            "metadataSource": {
                "fieldId": "automation_imports",
                "fieldName": None,
                "fieldType": None,
                "fieldOptions": None,
            },
        },
    ]


@pytest.mark.asyncio
async def test_list_automations_coerces_status_strings_to_enabled_booleans() -> None:
    settings = Settings.from_env(
        {
            "NETHUNT_EMAIL": "crm@example.com",
            "NETHUNT_API_KEY": "secret",
            "NETHUNT_AUTOMATION_COOKIE": "session=abc",
            "NETHUNT_AUTOMATION_MANIFEST_JSON": json.dumps(
                {
                    "workflow": {
                        "label": "Automations",
                        "name_path": "name",
                        "enabled_path": "status",
                        "operations": {
                            "list": {
                                "method": "GET",
                                "path": "/api/workflows",
                                "response_path": "items",
                            },
                            "get": {"method": "GET", "path": "/api/workflows/{automation_id}"},
                            "create": {"method": "POST", "path": "/api/workflows", "json": "$payload"},
                            "update": {"method": "PUT", "path": "/api/workflows/{automation_id}", "json": "$payload"},
                            "delete": {"method": "DELETE", "path": "/api/workflows/{automation_id}"},
                            "set_enabled": {"method": "PATCH", "path": "/api/workflows/{automation_id}/state"},
                        },
                    }
                }
            ),
        }
    )
    automation_client = FakeAutomationClient(
        responses={
            (
                "GET",
                "/api/workflows",
            ): {
                "items": [
                    {"id": "wf-active", "name": "Active automation", "status": "ACTIVE"},
                    {"id": "wf-initial", "name": "Draft automation", "status": "INITIAL"},
                ]
            }
        }
    )
    service = NetHuntService(FakeClient(), settings, automation_client=automation_client)

    result = await service.list_automations(kind="workflow")

    assert result == [
        {
            "kind": "workflow",
            "automationId": "wf-active",
            "name": "Active automation",
            "enabled": True,
            "raw": {"id": "wf-active", "name": "Active automation", "status": "ACTIVE"},
            "imports": [],
            "fieldReferences": [],
            "referenceCount": 0,
        },
        {
            "kind": "workflow",
            "automationId": "wf-initial",
            "name": "Draft automation",
            "enabled": False,
            "raw": {"id": "wf-initial", "name": "Draft automation", "status": "INITIAL"},
            "imports": [],
            "fieldReferences": [],
            "referenceCount": 0,
        },
    ]


@pytest.mark.asyncio
async def test_create_automation_requires_confirmation_to_execute() -> None:
    automation_client = FakeAutomationClient(
        responses={
            ("POST", "/api/workflows"): {
                "item": {"id": "wf-1", "attributes": {"name": "Welcome", "enabled": True}}
            }
        }
    )
    service = NetHuntService(FakeClient(), make_automation_settings(), automation_client=automation_client)
    payload = {"attributes": {"name": "Welcome", "enabled": True}}

    preview = await service.create_automation("workflow", payload, confirm_write=False)
    executed = await service.create_automation("workflow", payload, confirm_write=True)

    assert preview["executed"] is False
    assert preview["preview"]["path"] == "/api/workflows"
    assert executed["executed"] is True
    assert executed["result"]["automationId"] == "wf-1"
    assert automation_client.calls == [
        ("POST", "/api/workflows", None, payload, False),
    ]


@pytest.mark.asyncio
async def test_create_automation_refetches_by_name_when_response_has_no_identifier() -> None:
    automation_client = FakeAutomationClient(
        responses={
            ("POST", "/api/workflows"): {"status": "SUCCESS", "result": True},
            ("GET", "/api/workflows"): {
                "items": [
                    {"id": "wf-older", "attributes": {"name": "Welcome", "enabled": False}, "createdAt": 1},
                    {"id": "wf-1", "attributes": {"name": "Welcome", "enabled": True}, "createdAt": 2},
                ]
            },
        }
    )
    service = NetHuntService(FakeClient(), make_automation_settings(), automation_client=automation_client)
    payload = {"attributes": {"name": "Welcome", "enabled": True}}

    result = await service.create_automation("workflow", payload, confirm_write=True)

    assert result == {
        "executed": True,
        "result": {
            "kind": "workflow",
            "automationId": "wf-1",
            "name": "Welcome",
            "enabled": True,
            "raw": {
                "id": "wf-1",
                "attributes": {"name": "Welcome", "enabled": True},
                "createdAt": 2,
            },
            "imports": [],
            "fieldReferences": [],
            "referenceCount": 0,
        },
    }
    assert automation_client.calls == [
        ("POST", "/api/workflows", None, payload, False),
        ("GET", "/api/workflows", None, None, True),
    ]


@pytest.mark.asyncio
async def test_get_automation_can_include_branches() -> None:
    automation_client = FakeAutomationClient(
        responses={
            (
                "GET",
                "/api/workflows/wf-1",
            ): {
                "item": {
                    "id": "wf-1",
                    "attributes": {"name": "Welcome", "enabled": True},
                },
                "result": {
                    "branches": [
                        {
                            "branchNum": 1,
                            "steps": [
                                {
                                    "stepNum": 1,
                                    "role": "TRIGGER",
                                    "type": "RECORD_CREATED",
                                    "options": {"folderId": "folder-1", "fieldId": "41"},
                                }
                            ],
                        }
                    ]
                },
            }
        }
    )
    service = NetHuntService(FakeClient(), make_automation_settings(), automation_client=automation_client)

    result = await service.get_automation("workflow", "wf-1", include_branches=True)

    assert result["kind"] == "workflow"
    assert result["automationId"] == "wf-1"
    assert result["imports"] == []
    assert result["referenceCount"] == 1
    assert result["branches"][0]["branchId"] == "1"
    assert result["branches"][0]["stepCount"] == 1
    assert result["branches"][0]["steps"][0]["stepId"] == "1"
    assert result["branches"][0]["steps"][0]["targetFolderId"] == "folder-1"
    assert result["branches"][0]["steps"][0]["fieldReferences"] == [
        {
            "source": "step_options",
            "fieldPath": "branches[1].steps[1].options",
            "folderId": "folder-1",
            "fieldId": "41",
            "branchId": "1",
            "branchNum": 1,
            "stepId": "1",
            "stepNum": 1,
            "relation": None,
        }
    ]
    assert result["fieldReferences"] == result["branches"][0]["steps"][0]["fieldReferences"]
    assert result["branchGraph"] == {
        "branchCount": 1,
        "stepCount": 1,
        "branches": [{"branchId": "1", "branchNum": 1, "stepCount": 1}],
        "steps": [
            {
                "branchId": "1",
                "branchNum": 1,
                "stepId": "1",
                "stepNum": 1,
                "role": "TRIGGER",
                "type": "RECORD_CREATED",
            }
        ],
        "edges": [],
    }


@pytest.mark.asyncio
async def test_get_automation_maps_not_found_error_envelope() -> None:
    automation_client = FakeAutomationClient(
        responses={
            (
                "GET",
                "/api/workflows/wf-missing",
            ): {
                "status": "ERROR",
                "error": {
                    "code": "NotFoundError",
                    "message": "No automation wf-missing found",
                },
            }
        }
    )
    service = NetHuntService(FakeClient(), make_automation_settings(), automation_client=automation_client)

    with pytest.raises(NethuntMCPError) as exc_info:
        await service.get_automation("workflow", "wf-missing")

    assert exc_info.value.code == "not_found"
    assert exc_info.value.message == "No automation wf-missing found"


@pytest.mark.asyncio
async def test_delete_automation_returns_preview_without_confirm() -> None:
    automation_client = FakeAutomationClient(
        responses={
            (
                "GET",
                "/api/workflows/wf-1",
            ): {
                "item": {"id": "wf-1", "attributes": {"name": "Welcome", "enabled": True}}
            }
        }
    )
    service = NetHuntService(FakeClient(), make_automation_settings(), automation_client=automation_client)

    result = await service.delete_automation("workflow", "wf-1", confirm=False, preview_only=True)

    assert result["deleted"] is False
    assert result["preview"]["automation"]["automationId"] == "wf-1"
    assert automation_client.calls == [
        ("GET", "/api/workflows/wf-1", None, None, True),
    ]


@pytest.mark.asyncio
async def test_set_automation_enabled_renders_manifest_template() -> None:
    automation_client = FakeAutomationClient(
        responses={
            (
                "PATCH",
                "/api/workflows/wf-1/state",
            ): {
                "item": {"id": "wf-1", "attributes": {"name": "Welcome", "enabled": False}}
            }
        }
    )
    service = NetHuntService(FakeClient(), make_automation_settings(), automation_client=automation_client)

    result = await service.set_automation_enabled("workflow", "wf-1", False, confirm_write=True)

    assert result["executed"] is True
    assert result["result"]["enabled"] is False
    assert automation_client.calls == [
        ("PATCH", "/api/workflows/wf-1/state", None, {"enabled": False}, False),
    ]


@pytest.mark.asyncio
async def test_activate_automation_requires_confirmation_to_execute() -> None:
    automation_client = FakeAutomationClient(
        responses={
            ("POST", "/api/command"): {"ok": True},
        }
    )
    service = NetHuntService(FakeClient(), make_automation_settings(), automation_client=automation_client)

    preview = await service.activate_automation("workflow", "wf-1", confirm_write=False)
    executed = await service.activate_automation("workflow", "wf-1", confirm_write=True)

    assert preview["executed"] is False
    assert preview["preview"]["path"] == "/api/command"
    assert preview["preview"]["json"]["name"] == "activateAutomation"
    assert executed["executed"] is True
    assert executed["result"]["enabled"] is True
    assert automation_client.calls == [
        (
            "POST",
            "/api/command",
            None,
            {
                "service": "automation",
                "name": "activateAutomation",
                "data": {
                    "workspaceId": "6911d891768a235848ac5535",
                    "automationId": "wf-1",
                },
            },
            False,
        )
    ]


@pytest.mark.asyncio
async def test_rename_automation_renders_editor_manifest_template() -> None:
    automation_client = FakeAutomationClient(
        responses={
            ("POST", "/api/command"): {"ok": True},
        }
    )
    service = NetHuntService(FakeClient(), make_automation_settings(), automation_client=automation_client)

    result = await service.rename_automation("workflow", "wf-1", "Renamed", confirm_write=True)

    assert result["executed"] is True
    assert result["result"]["name"] == "Renamed"
    assert automation_client.calls == [
        (
            "POST",
            "/api/command",
            None,
            {
                "service": "automation",
                "name": "updateAutomationName",
                "data": {
                    "workspaceId": "6911d891768a235848ac5535",
                    "automationId": "wf-1",
                    "name": "Renamed",
                },
            },
            False,
        )
    ]


@pytest.mark.asyncio
async def test_get_automation_step_details_supports_list_options() -> None:
    automation_client = FakeAutomationClient(
        responses={
            ("POST", "/api/commands"): [
                {
                    "result": {
                        "stepId": "step-1",
                        "events": [],
                    }
                }
            ],
        }
    )
    service = NetHuntService(FakeClient(), make_automation_settings(), automation_client=automation_client)

    result = await service.get_automation_step_details(
        "workflow",
        "wf-1",
        2,
        list_options={"limit": 25},
    )

    assert result == {
        "stepId": "step-1",
        "events": [],
        "kind": "workflow",
        "automationId": "wf-1",
        "stepNum": 2,
        "listOptions": {"limit": 25},
    }
    assert automation_client.calls == [
        (
            "POST",
            "/api/commands",
            None,
            [
                {
                    "service": "automation",
                    "name": "getStepDetails",
                    "data": {
                        "workspaceId": "6911d891768a235848ac5535",
                        "automationId": "wf-1",
                        "stepNum": 2,
                        "listOptions": {"limit": 25},
                    },
                    "id": "90",
                }
            ],
            True,
        ),
        ("GET", "/api/workflows/wf-1", None, None, True),
    ]


@pytest.mark.asyncio
async def test_get_automation_step_details_enriches_branch_metadata_when_available() -> None:
    automation_client = FakeAutomationClient(
        responses={
            ("POST", "/api/commands"): [
                {
                    "result": {
                        "events": [],
                    }
                }
            ],
            (
                "GET",
                "/api/workflows/wf-1",
            ): {
                "item": {"id": "wf-1", "attributes": {"name": "Welcome", "enabled": True}},
                "result": {
                    "branches": [
                        {
                            "branchNum": 1,
                            "steps": [
                                {
                                    "stepNum": 2,
                                    "stepId": "step-2",
                                    "role": "ACTION",
                                    "type": "UPDATE_RECORD2",
                                    "options": {"folderId": "folder-1", "fieldId": "41"},
                                }
                            ],
                        }
                    ]
                },
            },
        }
    )
    service = NetHuntService(FakeClient(), make_automation_settings(), automation_client=automation_client)

    result = await service.get_automation_step_details("workflow", "wf-1", 2)

    assert result["branchId"] == "1"
    assert result["stepId"] == "step-2"
    assert result["role"] == "ACTION"
    assert result["type"] == "UPDATE_RECORD2"
    assert result["fieldReferences"] == [
        {
            "source": "step_options",
            "fieldPath": "branches[1].steps[2].options",
            "folderId": "folder-1",
            "fieldId": "41",
            "branchId": "1",
            "branchNum": 1,
            "stepId": "step-2",
            "stepNum": 2,
            "relation": None,
        }
    ]


@pytest.mark.asyncio
async def test_get_automation_step_details_uses_default_list_options() -> None:
    automation_client = FakeAutomationClient(
        responses={
            ("POST", "/api/commands"): [
                {
                    "result": {
                        "stepId": "step-1",
                        "events": [],
                    }
                }
            ],
        }
    )
    service = NetHuntService(FakeClient(), make_automation_settings(), automation_client=automation_client)

    result = await service.get_automation_step_details("workflow", "wf-1", 2)

    assert result == {
        "stepId": "step-1",
        "events": [],
        "kind": "workflow",
        "automationId": "wf-1",
        "stepNum": 2,
        "listOptions": {
            "sortBy": [{"key": "updatedAt", "asc": False}],
            "limit": 25,
        },
    }
    assert automation_client.calls == [
        (
            "POST",
            "/api/commands",
            None,
            [
                {
                    "service": "automation",
                    "name": "getStepDetails",
                    "data": {
                        "workspaceId": "6911d891768a235848ac5535",
                        "automationId": "wf-1",
                        "stepNum": 2,
                        "listOptions": {
                            "sortBy": [{"key": "updatedAt", "asc": False}],
                            "limit": 25,
                        },
                    },
                    "id": "90",
                }
            ],
            True,
        ),
        ("GET", "/api/workflows/wf-1", None, None, True),
    ]


@pytest.mark.asyncio
async def test_add_automation_step_renders_step_type_and_payload() -> None:
    automation_client = FakeAutomationClient(
        responses={
            ("POST", "/api/command"): {"ok": True},
        }
    )
    service = NetHuntService(FakeClient(), make_automation_settings(), automation_client=automation_client)

    result = await service.add_automation_step(
        "workflow",
        "wf-1",
        "SEND_EMAIL",
        {"templateId": "tmpl-1"},
        branch_id=1,
        role="ACTION",
        confirm_write=True,
    )

    assert result["executed"] is True
    assert result["result"]["stepType"] == "SEND_EMAIL"
    assert result["result"]["branchId"] == 1
    assert result["result"]["role"] == "ACTION"
    assert automation_client.calls == [
        (
            "POST",
            "/api/command",
            None,
            {
                "service": "automation",
                "name": "addStep",
                "data": {
                    "workspaceId": "6911d891768a235848ac5535",
                    "automationId": "wf-1",
                    "branchId": 1,
                    "role": "ACTION",
                    "type": "SEND_EMAIL",
                    "options": {"templateId": "tmpl-1"},
                },
            },
            False,
        )
    ]


@pytest.mark.asyncio
async def test_update_automation_step_renders_branch_id_and_payload() -> None:
    automation_client = FakeAutomationClient(
        responses={
            ("POST", "/api/command"): {"ok": True},
        }
    )
    service = NetHuntService(FakeClient(), make_automation_settings(), automation_client=automation_client)

    result = await service.update_automation_step(
        "workflow",
        "wf-1",
        3,
        {"unit": "DAYS", "amount": 3},
        branch_id=1,
        confirm_write=True,
    )

    assert result["executed"] is True
    assert result["result"]["stepNum"] == 3
    assert result["result"]["branchId"] == 1
    assert result["result"]["stepId"] == 3
    assert automation_client.calls == [
        (
            "POST",
            "/api/command",
            None,
            {
                "service": "automation",
                "name": "updateStepOptions",
                "data": {
                    "workspaceId": "6911d891768a235848ac5535",
                    "automationId": "wf-1",
                    "stepNum": 3,
                    "branchId": 1,
                    "stepId": 3,
                    "options": {"unit": "DAYS", "amount": 3},
                },
            },
            False,
        )
    ]


@pytest.mark.asyncio
async def test_delete_automation_step_supports_child_branch_num() -> None:
    automation_client = FakeAutomationClient(
        responses={
            ("POST", "/api/command"): {"ok": True},
        }
    )
    service = NetHuntService(FakeClient(), make_automation_settings(), automation_client=automation_client)

    result = await service.delete_automation_step(
        "workflow",
        "wf-1",
        3,
        child_branch_num=1,
        confirm_write=True,
    )

    assert result["executed"] is True
    assert result["result"]["childBranchNum"] == 1
    assert automation_client.calls == [
        (
            "POST",
            "/api/command",
            None,
            {
                "service": "automation",
                "name": "deleteStep",
                "data": {
                    "workspaceId": "6911d891768a235848ac5535",
                    "automationId": "wf-1",
                    "stepNum": 3,
                    "childBranchNum": 1,
                },
            },
            False,
        )
    ]


@pytest.mark.asyncio
async def test_automation_tools_require_cookie_and_manifest() -> None:
    service = NetHuntService(FakeClient(), make_settings(), automation_client=FakeAutomationClient())

    with pytest.raises(ConfigError):
        await service.list_automation_kinds()


@pytest.mark.asyncio
async def test_list_automations_supports_commands_array_payloads_and_indexed_response_paths() -> None:
    settings = Settings.from_env(
        {
            "NETHUNT_EMAIL": "crm@example.com",
            "NETHUNT_API_KEY": "secret",
            "NETHUNT_AUTOMATION_COOKIE": "session=abc",
            "NETHUNT_AUTOMATION_MANIFEST_JSON": json.dumps(
                {
                    "workflow": {
                        "label": "Workflows",
                        "name_path": "data.name",
                        "enabled_path": "data.enabled",
                        "operations": {
                            "list": {
                                "method": "POST",
                                "path": "/api/commands",
                                "json": [
                                    {
                                        "service": "automation",
                                        "name": "getWorkflows",
                                        "data": {"workspaceId": "6911d891768a235848ac5535"},
                                        "id": "1",
                                    }
                                ],
                                "response_path": "0.items",
                            },
                            "get": {"method": "GET", "path": "/noop/{automation_id}"},
                            "create": {"method": "POST", "path": "/noop", "json": "$payload"},
                            "update": {"method": "PUT", "path": "/noop/{automation_id}", "json": "$payload"},
                            "delete": {"method": "DELETE", "path": "/noop/{automation_id}"},
                            "set_enabled": {"method": "PATCH", "path": "/noop/{automation_id}/state"},
                        },
                    }
                }
            ),
        }
    )
    automation_client = FakeAutomationClient(
        responses={
            (
                "POST",
                "/api/commands",
            ): [
                {
                    "items": [
                        {"id": "wf-1", "data": {"name": "Welcome", "enabled": True}},
                    ]
                }
            ]
        }
    )
    service = NetHuntService(FakeClient(), settings, automation_client=automation_client)

    result = await service.list_automations(kind="workflow")

    assert result == [
        {
            "kind": "workflow",
            "automationId": "wf-1",
            "name": "Welcome",
            "enabled": True,
            "raw": {"id": "wf-1", "data": {"name": "Welcome", "enabled": True}},
            "imports": [],
            "fieldReferences": [],
            "referenceCount": 0,
        }
    ]
    assert automation_client.calls == [
        (
            "POST",
            "/api/commands",
            None,
            [{"service": "automation", "name": "getWorkflows", "data": {"workspaceId": "6911d891768a235848ac5535"}, "id": "1"}],
            True,
        )
    ]
