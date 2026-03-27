from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from copy import deepcopy
import json
import logging
from typing import Any, Callable

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import mcp.types as mcp_types

from .config import TelegramBotSettings

LOCAL_PREVIEW_ONLY_MUTATING_TOOL_NAMES = {
    "create_record",
    "update_record",
    "create_record_comment",
    "create_call_log",
}
CONFIRM_MUTATING_TOOL_NAMES = {"delete_record", "delete_automation"}
PREVIEW_ONLY_MUTATING_TOOL_NAMES = {"delete_record", "delete_automation"}
CONFIRM_WRITE_MUTATING_TOOL_NAMES = {
    "raw_post",
    "create_automation",
    "update_automation",
    "set_automation_enabled",
    "activate_automation",
    "deactivate_automation",
    "rename_automation",
    "add_automation_step",
    "update_automation_step",
    "delete_automation_step",
    "add_automation_split",
}
MUTATING_TOOL_NAMES = (
    LOCAL_PREVIEW_ONLY_MUTATING_TOOL_NAMES
    | CONFIRM_MUTATING_TOOL_NAMES
    | CONFIRM_WRITE_MUTATING_TOOL_NAMES
)
SERVER_PREVIEW_MUTATING_TOOL_NAMES = MUTATING_TOOL_NAMES - LOCAL_PREVIEW_ONLY_MUTATING_TOOL_NAMES
HIDDEN_MUTATION_CONTROL_FIELDS = {"confirm", "confirm_write", "preview_only"}


def is_mutating_tool(name: str) -> bool:
    return name in MUTATING_TOOL_NAMES


def build_preview_arguments(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    preview_arguments = dict(arguments or {})
    for field_name in HIDDEN_MUTATION_CONTROL_FIELDS:
        preview_arguments.pop(field_name, None)
    if name in CONFIRM_MUTATING_TOOL_NAMES:
        preview_arguments["confirm"] = False
    if name in CONFIRM_WRITE_MUTATING_TOOL_NAMES:
        preview_arguments["confirm_write"] = False
    if name in PREVIEW_ONLY_MUTATING_TOOL_NAMES:
        preview_arguments["preview_only"] = True
    return preview_arguments


def build_execute_arguments(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    execute_arguments = dict(arguments or {})
    execute_arguments.pop("preview_only", None)
    execute_arguments.pop("confirm", None)
    execute_arguments.pop("confirm_write", None)
    if name in CONFIRM_MUTATING_TOOL_NAMES:
        execute_arguments["confirm"] = True
    if name in CONFIRM_WRITE_MUTATING_TOOL_NAMES:
        execute_arguments["confirm_write"] = True
    return execute_arguments


def build_local_preview_result(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": "confirmation_required",
            "message": "This action requires approval before execution.",
            "details": {
                "preview": {
                    "toolName": name,
                    "arguments": arguments,
                }
            },
        },
    }


class McpToolBridge:
    def __init__(
        self,
        settings: TelegramBotSettings,
        *,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
        transport_factory: Callable[..., Any] = streamable_http_client,
        session_factory: type[ClientSession] = ClientSession,
    ) -> None:
        self.settings = settings
        self._http_client_factory = http_client_factory or self._build_http_client
        self._transport_factory = transport_factory
        self._session_factory = session_factory
        self._exit_stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._cached_tools: list[mcp_types.Tool] = []
        self._cached_openai_tools: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._logger = logging.getLogger("nethunt_mcp.mcp_bridge")

    async def start(self) -> None:
        await self._ensure_connected(refresh=True)

    async def close(self) -> None:
        async with self._lock:
            await self._close_unlocked()

    async def list_tools(self, *, refresh: bool = False) -> list[mcp_types.Tool]:
        await self._ensure_connected(refresh=refresh)
        return list(self._cached_tools)

    async def get_openai_tools(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        await self._ensure_connected(refresh=refresh)
        return deepcopy(self._cached_openai_tools)

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._call_with_reconnect(name, arguments)

    async def _call_with_reconnect(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                await self._ensure_connected(refresh=attempt == 1)
                if self._session is None:  # pragma: no cover - guarded by _ensure_connected
                    raise RuntimeError("MCP session was not initialized.")
                result = await self._session.call_tool(name, arguments)
                return _normalize_call_tool_result(result)
            except Exception as exc:
                last_error = exc
                self._logger.warning("MCP tool call failed for %s on attempt %s: %s", name, attempt + 1, exc)
                async with self._lock:
                    await self._close_unlocked()
        if last_error is None:  # pragma: no cover
            raise RuntimeError("MCP tool call failed unexpectedly without an error.")
        raise last_error

    async def _ensure_connected(self, *, refresh: bool = False) -> None:
        async with self._lock:
            if self._session is not None and not refresh:
                return
            await self._connect_unlocked()

    async def _connect_unlocked(self) -> None:
        await self._close_unlocked()
        stack = AsyncExitStack()
        try:
            http_client = self._http_client_factory()
            read_stream, write_stream, _ = await stack.enter_async_context(
                self._transport_factory(self.settings.telegram_mcp_url, http_client=http_client)
            )
            session = self._session_factory(read_stream, write_stream)
            await stack.enter_async_context(session)
            await session.initialize()
            tools_result = await session.list_tools()
        except Exception:
            await stack.aclose()
            raise

        self._exit_stack = stack
        self._session = session
        self._cached_tools = list(tools_result.tools)
        self._cached_openai_tools = [_tool_to_openai_function(tool) for tool in self._cached_tools]

    async def _close_unlocked(self) -> None:
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
        self._exit_stack = None
        self._session = None
        self._cached_tools = []
        self._cached_openai_tools = []

    def _build_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(headers=self.settings.mcp_auth_headers, timeout=60.0)


def _tool_to_openai_function(tool: mcp_types.Tool) -> dict[str, Any]:
    parameters = deepcopy(tool.inputSchema)
    if tool.name in MUTATING_TOOL_NAMES:
        parameters = _strip_mutation_control_fields(parameters)

    description = tool.description or f"Call the {tool.name} MCP tool."
    if tool.name in MUTATING_TOOL_NAMES:
        description = (
            f"{description} The host handles preview and user approval separately for this mutating action."
        )

    return {
        "type": "function",
        "name": tool.name,
        "description": description,
        "parameters": parameters,
        "strict": False,
    }


def _strip_mutation_control_fields(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for field_name in HIDDEN_MUTATION_CONTROL_FIELDS:
            properties.pop(field_name, None)
    required = schema.get("required")
    if isinstance(required, list):
        schema["required"] = [item for item in required if item not in HIDDEN_MUTATION_CONTROL_FIELDS]
        if not schema["required"]:
            schema.pop("required", None)
    return schema


def _normalize_call_tool_result(result: mcp_types.CallToolResult) -> dict[str, Any]:
    if result.structuredContent is not None:
        return result.structuredContent

    text_chunks: list[str] = []
    serialized_chunks: list[dict[str, Any]] = []
    for chunk in result.content:
        if getattr(chunk, "type", None) == "text" and hasattr(chunk, "text"):
            text_chunks.append(chunk.text)
        serialized_chunks.append(_serialize_content_block(chunk))

    if len(text_chunks) == 1:
        text = text_chunks[0]
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
        return {"ok": not result.isError, "content": text}

    return {"ok": not result.isError, "content": serialized_chunks}


def _serialize_content_block(chunk: Any) -> dict[str, Any]:
    if hasattr(chunk, "model_dump"):
        return chunk.model_dump(mode="json", by_alias=True, exclude_none=True)
    return {"value": repr(chunk)}
