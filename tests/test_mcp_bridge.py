from __future__ import annotations

import mcp.types as mcp_types

from nethunt_mcp.mcp_bridge import (
    build_execute_arguments,
    build_local_preview_result,
    build_preview_arguments,
    is_mutating_tool,
    _tool_to_openai_function,
)


def test_mutating_preview_arguments_strip_confirmation_fields() -> None:
    arguments = {
        "folder_id": "folder-1",
        "record_id": "record-1",
        "confirm": True,
        "preview_only": False,
    }

    preview_arguments = build_preview_arguments("delete_record", arguments)

    assert preview_arguments == {
        "folder_id": "folder-1",
        "record_id": "record-1",
        "confirm": False,
        "preview_only": True,
    }


def test_mutating_execute_arguments_restore_confirmation_fields() -> None:
    arguments = {
        "record_id": "record-1",
        "confirm_write": False,
        "preview_only": True,
    }

    execute_arguments = build_execute_arguments("raw_post", arguments)

    assert execute_arguments == {
        "record_id": "record-1",
        "confirm_write": True,
    }


def test_tool_to_openai_function_hides_mutation_controls() -> None:
    tool = mcp_types.Tool(
        name="delete_record",
        description="Delete a record.",
        inputSchema={
            "type": "object",
            "properties": {
                "folder_id": {"type": "string"},
                "record_id": {"type": "string"},
                "confirm": {"type": "boolean"},
                "preview_only": {"type": "boolean"},
            },
            "required": ["folder_id", "record_id", "confirm"],
        },
    )

    openai_tool = _tool_to_openai_function(tool)

    assert openai_tool["type"] == "function"
    assert openai_tool["name"] == "delete_record"
    assert "confirm" not in openai_tool["parameters"]["properties"]
    assert "preview_only" not in openai_tool["parameters"]["properties"]
    assert openai_tool["parameters"]["required"] == ["folder_id", "record_id"]


def test_local_preview_result_is_confirmation_guard() -> None:
    result = build_local_preview_result("create_record", {"folder_id": "folder-1"})

    assert result["ok"] is False
    assert result["error"]["code"] == "confirmation_required"
    assert result["error"]["details"]["preview"]["toolName"] == "create_record"


def test_is_mutating_tool_matches_known_write_tools() -> None:
    assert is_mutating_tool("create_record") is True
    assert is_mutating_tool("list_readable_folders") is False
