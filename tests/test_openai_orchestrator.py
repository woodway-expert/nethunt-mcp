from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from nethunt_mcp.config import TelegramBotSettings
from nethunt_mcp.openai_orchestrator import OpenAIOrchestrator


def make_bot_settings() -> TelegramBotSettings:
    return TelegramBotSettings.from_env(
        {
            "TELEGRAM_BOT_TOKEN": "telegram-token",
            "TELEGRAM_ALLOWED_USER_IDS": "123",
            "OPENAI_API_KEY": "openai-secret",
        }
    )


class FakeBridge:
    def __init__(self, *, openai_tools: list[dict[str, Any]] | None = None, tool_results: dict[str, Any] | None = None) -> None:
        self.openai_tools = openai_tools or []
        self.tool_results = tool_results or {}
        self.call_history: list[tuple[str, dict[str, Any]]] = []

    async def get_openai_tools(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        return self.openai_tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_arguments = arguments or {}
        self.call_history.append((name, normalized_arguments))
        key = f"{name}:{json.dumps(normalized_arguments, sort_keys=True)}"
        return self.tool_results[key]


class FakeResponsesAPI:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeOpenAIClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = FakeResponsesAPI(responses)

    async def close(self) -> None:
        return None


def make_function_call_response(response_id: str, *, name: str, call_id: str, arguments: str) -> Any:
    return SimpleNamespace(
        id=response_id,
        output=[
            {
                "type": "function_call",
                "name": name,
                "call_id": call_id,
                "arguments": arguments,
            }
        ],
        output_text="",
    )


def make_text_response(response_id: str, text: str) -> Any:
    return SimpleNamespace(
        id=response_id,
        output=[
            {
                "type": "message",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        output_text=text,
    )


@pytest.mark.asyncio
async def test_orchestrator_completes_read_only_tool_loop() -> None:
    bridge = FakeBridge(
        openai_tools=[
            {
                "type": "function",
                "name": "list_readable_folders",
                "description": "List folders",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        tool_results={
            'list_readable_folders:{}': {"ok": True, "data": [{"name": "Deals"}]},
        },
    )
    openai_client = FakeOpenAIClient(
        [
            make_function_call_response(
                "resp-1",
                name="list_readable_folders",
                call_id="call-1",
                arguments="{}",
            ),
            make_text_response("resp-2", "Folders: Deals"),
            make_text_response("resp-3", "Follow-up answer"),
        ]
    )
    orchestrator = OpenAIOrchestrator(make_bot_settings(), bridge, openai_client=openai_client)

    first_reply = await orchestrator.handle_user_message(123, "Show me the readable folders")
    second_reply = await orchestrator.handle_user_message(123, "And now answer without tools")

    assert first_reply.text == "Folders: Deals"
    assert first_reply.pending_action is None
    assert second_reply.text == "Follow-up answer"
    assert bridge.call_history == [("list_readable_folders", {})]
    assert openai_client.responses.calls[1]["previous_response_id"] == "resp-1"
    assert openai_client.responses.calls[1]["input"][0]["type"] == "function_call_output"
    assert openai_client.responses.calls[2]["previous_response_id"] == "resp-2"


@pytest.mark.asyncio
async def test_orchestrator_intercepts_mutating_tool_for_preview_and_execute() -> None:
    preview_arguments = {
        "folder_id": "folder-1",
        "record_id": "record-1",
        "confirm": False,
        "preview_only": True,
    }
    bridge = FakeBridge(
        openai_tools=[
            {
                "type": "function",
                "name": "delete_record",
                "description": "Delete a record",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "folder_id": {"type": "string"},
                        "record_id": {"type": "string"},
                    },
                },
            }
        ],
        tool_results={
            f'delete_record:{json.dumps(preview_arguments, sort_keys=True)}': {
                "ok": False,
                "error": {
                    "code": "confirmation_required",
                    "details": {"preview": {"recordId": "record-1"}},
                },
            },
            'delete_record:{"confirm": true, "folder_id": "folder-1", "record_id": "record-1"}': {
                "ok": True,
                "data": {"deleted": True},
            },
        },
    )
    openai_client = FakeOpenAIClient(
        [
            make_function_call_response(
                "resp-write",
                name="delete_record",
                call_id="call-delete",
                arguments='{"folder_id":"folder-1","record_id":"record-1","confirm":true}',
            ),
            make_text_response("resp-fresh", "Fresh question"),
        ]
    )
    orchestrator = OpenAIOrchestrator(make_bot_settings(), bridge, openai_client=openai_client)

    reply = await orchestrator.handle_user_message(123, "Delete record-1 from folder-1")
    fresh_reply = await orchestrator.handle_user_message(123, "New question after preview")
    execute_result = await orchestrator.execute_pending_action(reply.pending_action)  # type: ignore[arg-type]

    assert reply.pending_action is not None
    assert reply.text is None
    assert fresh_reply.text == "Fresh question"
    assert bridge.call_history[0] == ("delete_record", preview_arguments)
    assert reply.pending_action.execute_arguments == {
        "folder_id": "folder-1",
        "record_id": "record-1",
        "confirm": True,
    }
    assert bridge.call_history[1] == (
        "delete_record",
        {
            "folder_id": "folder-1",
            "record_id": "record-1",
            "confirm": True,
        },
    )
    assert execute_result["ok"] is True
    assert openai_client.responses.calls[1]["previous_response_id"] is None
