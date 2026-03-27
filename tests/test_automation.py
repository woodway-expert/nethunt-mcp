from __future__ import annotations

import pytest

from nethunt_mcp.automation import AutomationRegistry, render_template
from nethunt_mcp.errors import ConfigError, ValidationError


def make_manifest() -> dict[str, object]:
    return {
        "workflow": {
            "label": "Workflows",
            "operations": {
                "list": {"method": "GET", "path": "/api/workflows"},
                "get": {"method": "GET", "path": "/api/workflows/{automation_id}"},
                "create": {"method": "POST", "path": "/api/workflows", "json": "$payload"},
                "update": {"method": "PUT", "path": "/api/workflows/{automation_id}", "json": "$payload"},
                "delete": {"method": "DELETE", "path": "/api/workflows/{automation_id}"},
                "set_enabled": {"method": "PATCH", "path": "/api/workflows/{automation_id}/state"},
            },
            "editor_operations": {
                "activate": {
                    "method": "POST",
                    "path": "/api/command",
                    "json": {"name": "activateAutomation"},
                },
                "rename": {
                    "method": "POST",
                    "path": "/api/command",
                    "json": {"name": "updateAutomationName", "value": "$payload"},
                },
            },
        }
    }


def test_registry_capabilities_include_editor_operations() -> None:
    registry = AutomationRegistry.from_manifest(make_manifest())

    assert registry.capabilities() == [
        {
            "kind": "workflow",
            "label": "Workflows",
            "operations": ["create", "delete", "get", "list", "set_enabled", "update"],
            "editorOperations": ["activate", "rename"],
            "idPath": "id",
            "namePath": "name",
            "enabledPath": "enabled",
            "samples": {},
        }
    ]


def test_registry_resolve_operation_supports_editor_operations() -> None:
    registry = AutomationRegistry.from_manifest(make_manifest())
    spec = registry.require_kind("workflow")

    operation = spec.resolve_operation("rename", editor=True)

    assert operation.method == "POST"
    assert operation.path == "/api/command"


def test_registry_rejects_invalid_editor_operations_shape() -> None:
    manifest = make_manifest()
    manifest["workflow"] = {
        **manifest["workflow"],
        "editor_operations": [],
    }

    with pytest.raises(ConfigError):
        AutomationRegistry.from_manifest(manifest)


def test_registry_rejects_unknown_editor_operation_lookup() -> None:
    registry = AutomationRegistry.from_manifest(make_manifest())

    with pytest.raises(ValidationError):
        registry.require_kind("workflow").resolve_operation("missing", editor=True)


def test_render_template_injects_scalar_payload_keys() -> None:
    template = "/api/{service}/automations"
    context = {
        "kind": "workflow",
        "payload": {"service": "automation", "nested": {"key": "val"}},
    }

    result = render_template(template, context)

    assert result == "/api/automation/automations"


def test_render_template_error_lists_available_variables() -> None:
    template = "/api/{missing_var}/automations"
    context = {"kind": "workflow", "payload": {"service": "automation"}}

    with pytest.raises(ValidationError) as exc_info:
        render_template(template, context)

    assert exc_info.value.details is not None
    assert exc_info.value.details["missing"] == "missing_var"
    assert "available" in exc_info.value.details
    assert "kind" in exc_info.value.details["available"]
    assert "service" in exc_info.value.details["available"]


def test_render_template_payload_cannot_shadow_context_keys() -> None:
    template = "{kind}/test"
    context = {
        "kind": "workflow",
        "payload": {"kind": "OVERRIDDEN"},
    }

    result = render_template(template, context)

    assert result == "workflow/test"
