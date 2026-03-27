from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from .config import TelegramBotSettings
from .mcp_bridge import (
    LOCAL_PREVIEW_ONLY_MUTATING_TOOL_NAMES,
    McpToolBridge,
    build_execute_arguments,
    build_local_preview_result,
    build_preview_arguments,
    is_mutating_tool,
)

SYSTEM_PROMPT = (
    "You are a NetHunt CRM assistant for a private Telegram bot. "
    "Use MCP discovery and read tools first to inspect folders, fields, records, and automation data before acting. "
    "Never invent CRM state, record IDs, folder IDs, field IDs, or automation details. "
    "If required arguments are missing, ask a concise follow-up question instead of guessing. "
    "Use the available tools for CRM facts whenever possible. "
    "Do not claim that a mutating action succeeded until the host confirms execution. "
    "The host manages preview and approval for mutating actions outside the model."
)
MAX_TOOL_ROUNDS = 8


@dataclass(slots=True, frozen=True)
class PendingAction:
    user_id: int
    tool_name: str
    preview_arguments: dict[str, Any]
    execute_arguments: dict[str, Any]
    preview_result: dict[str, Any]


@dataclass(slots=True, frozen=True)
class OrchestratorReply:
    text: str | None = None
    pending_action: PendingAction | None = None


@dataclass(slots=True, frozen=True)
class ToolCallRequest:
    name: str
    call_id: str
    arguments: dict[str, Any]


class OpenAIOrchestrator:
    def __init__(
        self,
        settings: TelegramBotSettings,
        bridge: McpToolBridge,
        *,
        openai_client: AsyncOpenAI | Any | None = None,
        max_tool_rounds: int = MAX_TOOL_ROUNDS,
    ) -> None:
        self.settings = settings
        self.bridge = bridge
        self._client = openai_client or AsyncOpenAI(api_key=settings.openai_api_key)
        self._conversation_state: dict[int, str] = {}
        self._max_tool_rounds = max_tool_rounds
        self._logger = logging.getLogger("nethunt_mcp.openai_orchestrator")

    async def close(self) -> None:
        for method_name in ("close", "aclose"):
            close_method = getattr(self._client, method_name, None)
            if close_method is None:
                continue
            result = close_method()
            if inspect.isawaitable(result):
                await result
            return

    def reset_user(self, user_id: int) -> None:
        self._conversation_state.pop(user_id, None)

    async def handle_user_message(self, user_id: int, text: str) -> OrchestratorReply:
        previous_response_id = self._conversation_state.get(user_id)
        tools = await self.bridge.get_openai_tools()
        current_input: Any = text
        current_previous_response_id = previous_response_id

        for _ in range(self._max_tool_rounds):
            response = await self._client.responses.create(
                model=self.settings.openai_model,
                instructions=SYSTEM_PROMPT,
                previous_response_id=current_previous_response_id,
                input=current_input,
                tools=tools,
                tool_choice="auto",
                parallel_tool_calls=False,
            )

            tool_calls = _extract_function_calls(response)
            if not tool_calls:
                final_text = _extract_output_text(response) or "I couldn't produce a response for that request."
                self._conversation_state[user_id] = response.id
                return OrchestratorReply(text=final_text)

            if len(tool_calls) > 1:
                self._logger.warning("Model returned %s tool calls despite parallel_tool_calls=False", len(tool_calls))
                return OrchestratorReply(
                    text="I need a more specific request before I can continue. Please try again with one task at a time."
                )

            tool_call = tool_calls[0]
            raw_arguments = tool_call.arguments.pop("_raw", None)
            if raw_arguments is not None:
                current_input = [
                    {
                        "type": "function_call_output",
                        "call_id": tool_call.call_id,
                        "output": json.dumps(
                            {
                                "ok": False,
                                "error": {
                                    "code": "invalid_tool_arguments",
                                    "message": "The tool call arguments were not valid JSON.",
                                    "details": {"raw_arguments": raw_arguments},
                                },
                            },
                            ensure_ascii=False,
                        ),
                    }
                ]
                current_previous_response_id = response.id
                continue

            if is_mutating_tool(tool_call.name):
                preview_arguments = build_preview_arguments(tool_call.name, tool_call.arguments)
                execute_arguments = build_execute_arguments(tool_call.name, tool_call.arguments)
                if tool_call.name in LOCAL_PREVIEW_ONLY_MUTATING_TOOL_NAMES:
                    preview_result = build_local_preview_result(tool_call.name, preview_arguments)
                else:
                    try:
                        preview_result = await self.bridge.call_tool(tool_call.name, preview_arguments)
                    except Exception as exc:
                        self._logger.exception("Failed to prepare preview for %s", tool_call.name)
                        return OrchestratorReply(
                            text=f"I couldn't prepare that action because the MCP bridge failed: {exc}"
                        )
                return OrchestratorReply(
                    pending_action=PendingAction(
                        user_id=user_id,
                        tool_name=tool_call.name,
                        preview_arguments=preview_arguments,
                        execute_arguments=execute_arguments,
                        preview_result=preview_result,
                    )
                )

            try:
                tool_result = await self.bridge.call_tool(tool_call.name, tool_call.arguments)
            except Exception as exc:
                self._logger.exception("Read tool call failed for %s", tool_call.name)
                tool_result = {
                    "ok": False,
                    "error": {
                        "code": "tool_execution_failed",
                        "message": str(exc),
                    },
                }
            current_input = [
                {
                    "type": "function_call_output",
                    "call_id": tool_call.call_id,
                    "output": json.dumps(tool_result, ensure_ascii=False),
                }
            ]
            current_previous_response_id = response.id

        return OrchestratorReply(
            text="I hit the tool-call limit for that request. Please rephrase it and try again."
        )

    async def execute_pending_action(self, pending_action: PendingAction) -> dict[str, Any]:
        return await self.bridge.call_tool(pending_action.tool_name, pending_action.execute_arguments)


def _extract_function_calls(response: Any) -> list[ToolCallRequest]:
    tool_calls: list[ToolCallRequest] = []
    for item in _iter_output_items(response):
        if _get_field(item, "type") != "function_call":
            continue
        tool_name = _get_field(item, "name")
        call_id = _get_field(item, "call_id")
        raw_arguments = _get_field(item, "arguments") or "{}"
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            arguments = {"_raw": raw_arguments}
        if not isinstance(arguments, dict):
            arguments = {"value": arguments}
        if not tool_name or not call_id:
            continue
        tool_calls.append(
            ToolCallRequest(
                name=tool_name,
                call_id=call_id,
                arguments=arguments,
            )
        )
    return tool_calls


def _extract_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    text_parts: list[str] = []
    for item in _iter_output_items(response):
        if _get_field(item, "type") != "message":
            continue
        for content_item in _get_field(item, "content", []) or []:
            if _get_field(content_item, "type") == "output_text":
                text_value = _get_field(content_item, "text")
                if isinstance(text_value, str) and text_value.strip():
                    text_parts.append(text_value.strip())
    return "\n\n".join(text_parts).strip()


def _iter_output_items(response: Any) -> list[Any]:
    output = getattr(response, "output", None)
    if isinstance(output, list):
        return output
    return []


def _get_field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)
