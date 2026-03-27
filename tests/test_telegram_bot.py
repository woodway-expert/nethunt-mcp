from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from nethunt_mcp.config import TelegramBotSettings
from nethunt_mcp.openai_orchestrator import OrchestratorReply, PendingAction
from nethunt_mcp.telegram_bot import (
    AccessMiddleware,
    CANCELLED_TEXT,
    PENDING_EXPIRED_TEXT,
    PendingActionStore,
    RESET_TEXT,
    TelegramBotApp,
)


def make_bot_settings() -> TelegramBotSettings:
    return TelegramBotSettings.from_env(
        {
            "TELEGRAM_BOT_TOKEN": "telegram-token",
            "TELEGRAM_ALLOWED_USER_IDS": "123",
            "OPENAI_API_KEY": "openai-secret",
        }
    )


class FakeBridge:
    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeOrchestrator:
    def __init__(self, replies: list[OrchestratorReply] | None = None) -> None:
        self._replies = list(replies or [])
        self.handle_calls: list[tuple[int, str]] = []
        self.execute_calls: list[PendingAction] = []
        self.reset_calls: list[int] = []

    async def handle_user_message(self, user_id: int, text: str) -> OrchestratorReply:
        self.handle_calls.append((user_id, text))
        return self._replies.pop(0)

    async def execute_pending_action(self, pending_action: PendingAction) -> dict[str, Any]:
        self.execute_calls.append(pending_action)
        return {"ok": True, "data": {"executed": True}}

    def reset_user(self, user_id: int) -> None:
        self.reset_calls.append(user_id)

    async def close(self) -> None:
        return None


class FakeBot:
    def __init__(self) -> None:
        self.session = SimpleNamespace(close=self._close)

    async def set_my_commands(self, commands: list[Any]) -> None:
        return None

    async def _close(self) -> None:
        return None


class FakeEvent:
    def __init__(self, *, chat_type: str, user_id: int) -> None:
        self.chat = SimpleNamespace(type=chat_type)
        self.from_user = SimpleNamespace(id=user_id)


@pytest.mark.asyncio
async def test_access_middleware_replies_for_unauthorized_private_user(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[FakeEvent] = []

    async def fake_reply(event: FakeEvent) -> None:
        calls.append(event)

    middleware = AccessMiddleware(frozenset({123}))
    handler_called = False

    async def handler(event: Any, data: dict[str, Any]) -> None:
        nonlocal handler_called
        handler_called = True

    monkeypatch.setattr("nethunt_mcp.telegram_bot._reply_unauthorized", fake_reply)

    await middleware(handler, FakeEvent(chat_type="private", user_id=999), {})

    assert len(calls) == 1
    assert handler_called is False


@pytest.mark.asyncio
async def test_access_middleware_ignores_group_chats(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[FakeEvent] = []

    async def fake_reply(event: FakeEvent) -> None:
        calls.append(event)

    middleware = AccessMiddleware(frozenset({123}))
    handler_called = False

    async def handler(event: Any, data: dict[str, Any]) -> None:
        nonlocal handler_called
        handler_called = True

    monkeypatch.setattr("nethunt_mcp.telegram_bot._reply_unauthorized", fake_reply)

    await middleware(handler, FakeEvent(chat_type="group", user_id=123), {})

    assert calls == []
    assert handler_called is False


@pytest.mark.asyncio
async def test_telegram_bot_read_only_flow_returns_text_reply() -> None:
    orchestrator = FakeOrchestrator(replies=[OrchestratorReply(text="Folders: Deals")])
    app = TelegramBotApp(
        make_bot_settings(),
        bridge=FakeBridge(),
        orchestrator=orchestrator,
        pending_store=PendingActionStore(),
        bot=FakeBot(),
    )

    reply = await app.handle_text_request(123, "Show folders")

    assert reply.text == "Folders: Deals"
    assert orchestrator.handle_calls == [(123, "Show folders")]


def test_reset_user_clears_pending_actions_and_conversation() -> None:
    orchestrator = FakeOrchestrator()
    pending_store = PendingActionStore()
    app = TelegramBotApp(
        make_bot_settings(),
        bridge=FakeBridge(),
        orchestrator=orchestrator,
        pending_store=pending_store,
        bot=FakeBot(),
    )
    pending_store.add(
        PendingAction(
            user_id=123,
            tool_name="delete_record",
            preview_arguments={"record_id": "record-1"},
            execute_arguments={"record_id": "record-1", "confirm": True},
            preview_result={"ok": False},
        )
    )

    result = app.reset_user(123)

    assert result == RESET_TEXT
    assert pending_store.get_for_user(123) is None
    assert orchestrator.reset_calls == [123]


@pytest.mark.asyncio
async def test_cancel_and_expiry_prevent_execution() -> None:
    orchestrator = FakeOrchestrator()
    pending_store = PendingActionStore()
    app = TelegramBotApp(
        make_bot_settings(),
        bridge=FakeBridge(),
        orchestrator=orchestrator,
        pending_store=pending_store,
        bot=FakeBot(),
    )
    active_entry = pending_store.add(
        PendingAction(
            user_id=123,
            tool_name="delete_record",
            preview_arguments={"record_id": "record-1"},
            execute_arguments={"record_id": "record-1", "confirm": True},
            preview_result={"ok": False},
        )
    )

    cancel_reply = app.cancel_pending_action(123, active_entry.token)

    assert cancel_reply.text == CANCELLED_TEXT
    assert orchestrator.execute_calls == []

    expired_entry = pending_store.add(
        PendingAction(
            user_id=123,
            tool_name="delete_record",
            preview_arguments={"record_id": "record-2"},
            execute_arguments={"record_id": "record-2", "confirm": True},
            preview_result={"ok": False},
        )
    )
    pending_store._entries_by_token[expired_entry.token] = replace(
        expired_entry,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    expired_reply = await app.approve_pending_action(123, expired_entry.token)

    assert expired_reply.text == PENDING_EXPIRED_TEXT
    assert orchestrator.execute_calls == []
