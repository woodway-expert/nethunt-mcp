from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import html
import json
import logging
import secrets
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)

from .config import TelegramBotSettings
from .mcp_bridge import McpToolBridge
from .openai_orchestrator import OpenAIOrchestrator, OrchestratorReply, PendingAction

UNAUTHORIZED_TEXT = "This bot is not available for your account."
START_TEXT = (
    "Natural-language NetHunt control is ready.\n\n"
    "Send a request in plain English and I’ll use the MCP tools when needed. "
    "Mutating actions always stop for approval before execution.\n\n"
    "Commands: /help, /reset"
)
HELP_TEXT = (
    "Send a plain-English NetHunt request in this private chat.\n\n"
    "I can inspect folders, fields, records, and automations. "
    "If an action would change CRM data, I’ll send a deterministic preview and wait for your approval.\n\n"
    "Use /reset to clear conversation memory and discard any pending approval."
)
RESET_TEXT = "Conversation memory and pending approvals were cleared."
PENDING_EXISTS_TEXT = (
    "You already have a pending action waiting for approval. "
    "Approve or cancel it below, or use /reset to discard it."
)
PENDING_NOT_FOUND_TEXT = "That pending action is no longer available."
PENDING_EXPIRED_TEXT = "That pending action expired and was discarded."
CANCELLED_TEXT = "The pending action was cancelled."
PENDING_TTL = timedelta(minutes=15)


@dataclass(slots=True, frozen=True)
class PendingActionEntry:
    token: str
    action: PendingAction
    created_at: datetime
    expires_at: datetime

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at


@dataclass(slots=True, frozen=True)
class ChatReply:
    text: str
    reply_markup: InlineKeyboardMarkup | None = None


class PendingActionStore:
    def __init__(self, *, ttl: timedelta = PENDING_TTL) -> None:
        self._ttl = ttl
        self._entries_by_token: dict[str, PendingActionEntry] = {}
        self._token_by_user_id: dict[int, str] = {}

    def add(self, action: PendingAction) -> PendingActionEntry:
        self.clear_user(action.user_id)
        created_at = datetime.now(UTC)
        entry = PendingActionEntry(
            token=secrets.token_urlsafe(8),
            action=action,
            created_at=created_at,
            expires_at=created_at + self._ttl,
        )
        self._entries_by_token[entry.token] = entry
        self._token_by_user_id[action.user_id] = entry.token
        return entry

    def get_for_user(self, user_id: int) -> PendingActionEntry | None:
        token = self._token_by_user_id.get(user_id)
        if token is None:
            return None
        return self.get(token)

    def get(self, token: str) -> PendingActionEntry | None:
        entry = self._entries_by_token.get(token)
        if entry is None:
            return None
        if entry.is_expired:
            self.remove(token)
            return None
        return entry

    def take(self, token: str, *, user_id: int) -> PendingActionEntry | None:
        entry = self.get(token)
        if entry is None or entry.action.user_id != user_id:
            return None
        self.remove(token)
        return entry

    def remove(self, token: str) -> None:
        entry = self._entries_by_token.pop(token, None)
        if entry is None:
            return
        self._token_by_user_id.pop(entry.action.user_id, None)

    def clear_user(self, user_id: int) -> None:
        token = self._token_by_user_id.pop(user_id, None)
        if token is not None:
            self._entries_by_token.pop(token, None)


class AccessMiddleware(BaseMiddleware):
    def __init__(self, allowed_user_ids: frozenset[int]) -> None:
        self._allowed_user_ids = allowed_user_ids

    async def __call__(self, handler: Any, event: TelegramObject, data: dict[str, Any]) -> Any:
        chat, user = _extract_chat_and_user(event)
        if chat is None or user is None:
            return None
        if chat.type != ChatType.PRIVATE:
            return None
        if user.id not in self._allowed_user_ids:
            await _reply_unauthorized(event)
            return None
        data["authorized_user_id"] = user.id
        return await handler(event, data)


class TelegramBotApp:
    def __init__(
        self,
        settings: TelegramBotSettings,
        *,
        bridge: McpToolBridge | None = None,
        orchestrator: OpenAIOrchestrator | None = None,
        pending_store: PendingActionStore | None = None,
        bot: Bot | None = None,
    ) -> None:
        self.settings = settings
        self.bridge = bridge or McpToolBridge(settings)
        self.orchestrator = orchestrator or OpenAIOrchestrator(settings, self.bridge)
        self.pending_store = pending_store or PendingActionStore()
        self.bot = bot or Bot(
            token=settings.telegram_bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self.dispatcher = Dispatcher()
        self.router = Router()
        self._logger = logging.getLogger("nethunt_mcp.telegram_bot")
        self._configure_router()

    async def run(self) -> None:
        await self.bridge.start()
        await self.bot.set_my_commands(
            [
                BotCommand(command="help", description="Show usage help"),
                BotCommand(command="reset", description="Clear conversation and pending approvals"),
            ]
        )
        try:
            await self.dispatcher.start_polling(self.bot)
        finally:
            await self.close()

    async def close(self) -> None:
        await self.orchestrator.close()
        await self.bridge.close()
        await self.bot.session.close()

    async def handle_text_request(self, user_id: int, text: str) -> ChatReply:
        pending_entry = self.pending_store.get_for_user(user_id)
        if pending_entry is not None:
            return ChatReply(
                text=PENDING_EXISTS_TEXT,
                reply_markup=_build_approval_keyboard(pending_entry.token),
            )

        reply = await self.orchestrator.handle_user_message(user_id, text)
        if reply.pending_action is not None:
            entry = self.pending_store.add(reply.pending_action)
            return ChatReply(
                text=_render_preview_message(entry),
                reply_markup=_build_approval_keyboard(entry.token),
            )
        return ChatReply(text=reply.text or "I couldn't produce a reply for that request.")

    async def approve_pending_action(self, user_id: int, token: str) -> ChatReply:
        existing_entry = self.pending_store._entries_by_token.get(token)
        if existing_entry is None or existing_entry.action.user_id != user_id:
            return ChatReply(text=PENDING_NOT_FOUND_TEXT)
        if existing_entry.is_expired:
            self.pending_store.remove(token)
            return ChatReply(text=PENDING_EXPIRED_TEXT)
        entry = self.pending_store.take(token, user_id=user_id)
        if entry is None:
            return ChatReply(text=PENDING_NOT_FOUND_TEXT)
        result = await self.orchestrator.execute_pending_action(entry.action)
        return ChatReply(text=_render_execution_message(entry, result))

    def cancel_pending_action(self, user_id: int, token: str) -> ChatReply:
        existing_entry = self.pending_store._entries_by_token.get(token)
        if existing_entry is None or existing_entry.action.user_id != user_id:
            return ChatReply(text=PENDING_NOT_FOUND_TEXT)
        if existing_entry.is_expired:
            self.pending_store.remove(token)
            return ChatReply(text=PENDING_EXPIRED_TEXT)
        self.pending_store.remove(token)
        return ChatReply(text=CANCELLED_TEXT)

    def reset_user(self, user_id: int) -> str:
        self.orchestrator.reset_user(user_id)
        self.pending_store.clear_user(user_id)
        return RESET_TEXT

    def _configure_router(self) -> None:
        access_middleware = AccessMiddleware(self.settings.telegram_allowed_user_ids)
        self.router.message.outer_middleware(access_middleware)
        self.router.callback_query.outer_middleware(access_middleware)

        self.router.message.register(self._handle_start, CommandStart())
        self.router.message.register(self._handle_help, Command("help"))
        self.router.message.register(self._handle_reset, Command("reset"))
        self.router.message.register(self._handle_text, F.text)
        self.router.callback_query.register(self._handle_approve, F.data.startswith("approve:"))
        self.router.callback_query.register(self._handle_cancel, F.data.startswith("cancel:"))
        self.dispatcher.include_router(self.router)

    async def _handle_start(self, message: Message) -> None:
        await message.answer(START_TEXT)

    async def _handle_help(self, message: Message) -> None:
        await message.answer(HELP_TEXT)

    async def _handle_reset(self, message: Message, authorized_user_id: int) -> None:
        await message.answer(self.reset_user(authorized_user_id))

    async def _handle_text(self, message: Message, authorized_user_id: int) -> None:
        if message.text is None:
            return
        reply = await self.handle_text_request(authorized_user_id, message.text)
        await message.answer(reply.text, reply_markup=reply.reply_markup)

    async def _handle_approve(self, callback_query: CallbackQuery, authorized_user_id: int) -> None:
        token = callback_query.data.split(":", 1)[1]
        reply = await self.approve_pending_action(authorized_user_id, token)
        await callback_query.answer("Action processed.")
        await _clear_reply_markup(callback_query)
        if callback_query.message is not None:
            await callback_query.message.answer(reply.text)

    async def _handle_cancel(self, callback_query: CallbackQuery, authorized_user_id: int) -> None:
        token = callback_query.data.split(":", 1)[1]
        reply = self.cancel_pending_action(authorized_user_id, token)
        await callback_query.answer("Pending action updated.")
        await _clear_reply_markup(callback_query)
        if callback_query.message is not None:
            await callback_query.message.answer(reply.text)


def _build_approval_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Approve", callback_data=f"approve:{token}"),
                InlineKeyboardButton(text="Cancel", callback_data=f"cancel:{token}"),
            ]
        ]
    )


def _extract_chat_and_user(event: TelegramObject) -> tuple[Any | None, Any | None]:
    chat = getattr(event, "chat", None)
    user = getattr(event, "from_user", None)
    if chat is not None and user is not None:
        return chat, user
    message = getattr(event, "message", None)
    if message is not None:
        return getattr(message, "chat", None), getattr(event, "from_user", None) or getattr(message, "from_user", None)
    return None, None


async def _reply_unauthorized(event: TelegramObject) -> None:
    if isinstance(event, Message):
        await event.answer(UNAUTHORIZED_TEXT)
        return
    if isinstance(event, CallbackQuery):
        await event.answer(UNAUTHORIZED_TEXT, show_alert=True)


async def _clear_reply_markup(callback_query: CallbackQuery) -> None:
    if callback_query.message is None:
        return
    try:
        await callback_query.message.edit_reply_markup(reply_markup=None)
    except Exception:  # pragma: no cover - Telegram rejects no-op edits
        return


def _render_preview_message(entry: PendingActionEntry) -> str:
    preview_payload = (
        entry.action.preview_result.get("error", {}).get("details", {}).get("preview")
        or entry.action.preview_result
    )
    expires_in = max(int((entry.expires_at - datetime.now(UTC)).total_seconds() // 60), 0)
    return (
        f"Approval required for <code>{html.escape(entry.action.tool_name)}</code>.\n\n"
        f"Preview:\n<pre>{_format_json_block(preview_payload)}</pre>\n\n"
        f"Expires in {expires_in} minute(s)."
    )


def _render_execution_message(entry: PendingActionEntry, result: dict[str, Any]) -> str:
    status = "Execution completed" if result.get("ok", True) else "Execution returned an error"
    return (
        f"{status} for <code>{html.escape(entry.action.tool_name)}</code>.\n\n"
        f"Result:\n<pre>{_format_json_block(result)}</pre>"
    )


def _format_json_block(payload: Any, *, limit: int = 3000) -> str:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    if len(text) > limit:
        text = f"{text[:limit - 15].rstrip()}\n...<truncated>"
    return html.escape(text)
