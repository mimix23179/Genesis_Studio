from __future__ import annotations

import asyncio
import threading
from typing import Any, Awaitable, Callable

from ..providers import OllamaProvider
from .session_service import SessionService

Notifier = Callable[[str, dict[str, Any]], Awaitable[None]]


class ChatService:
    """Chat orchestration service decoupled from WebSocket transport."""

    def __init__(
        self,
        *,
        session_service: SessionService,
        provider: OllamaProvider,
        notify: Notifier,
    ) -> None:
        self._sessions = session_service
        self._provider = provider
        self._notify = notify

    async def send(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = str(params.get("session_id", "")).strip()
        session = self._sessions.require_session(session_id)

        message = params.get("message", {}) if isinstance(params.get("message"), dict) else {}
        user_text = self._provider.extract_message_text(message)
        if not user_text:
            raise ValueError("Empty user message")

        self._sessions.append_user_message(session_id, user_text)
        assistant_id = self._sessions.new_message_id()

        await self._notify("chat.begin", {"session_id": session_id, "message_id": assistant_id})

        assistant_text = ""
        history = self._sessions.messages_for_model(session_id)
        loop = asyncio.get_running_loop()
        stream_queue: asyncio.Queue[str | None] = asyncio.Queue()

        def _pump_stream() -> None:
            try:
                for piece in self._provider.collect_stream(history):
                    asyncio.run_coroutine_threadsafe(stream_queue.put(piece), loop)
            finally:
                asyncio.run_coroutine_threadsafe(stream_queue.put(None), loop)

        threading.Thread(target=_pump_stream, daemon=True, name="genesis-chat-stream").start()

        async def emit_answer_char(character: str) -> None:
            nonlocal assistant_text
            if not character:
                return
            assistant_text += character
            await self._notify(
                "chat.delta",
                {"session_id": session_id, "message_id": assistant_id, "delta": character},
            )
            await asyncio.sleep(0)

        while True:
            chunk = await stream_queue.get()
            if chunk is None:
                break
            for character in chunk:
                await emit_answer_char(character)

        assistant_item = self._sessions.append_assistant_message(
            session_id,
            assistant_text,
            message_id=assistant_id,
        )

        if self._should_auto_title(session):
            suggested_title = self._provider.suggest_session_title(user_text)
            renamed = self._sessions.rename_session(session_id, suggested_title)
            await self._notify(
                "session.updated",
                {
                    "session_id": session_id,
                    "action": "renamed",
                    "title": renamed["title"],
                },
            )

        await self._notify("chat.message", {"session_id": session_id, "message": assistant_item})
        await self._notify("session.updated", {"session_id": session_id, "action": "message"})

        return {"ok": True, "session_id": session_id, "message_id": assistant_id}

    @staticmethod
    def _should_auto_title(session: dict[str, Any]) -> bool:
        title = str(session.get("title", "")).strip().lower()
        messages = session.get("messages", [])
        user_message_count = len(
            [item for item in messages if isinstance(item, dict) and str(item.get("role", "")).strip() == "user"]
        )
        return title in {"", "new conversation", "new chat"} and user_message_count <= 1
