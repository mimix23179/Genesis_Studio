from __future__ import annotations

import asyncio
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
        self._sessions.require_session(session_id)

        message = params.get("message", {}) if isinstance(params.get("message"), dict) else {}
        user_text = self._provider.extract_message_text(message)
        if not user_text:
            raise ValueError("Empty user message")

        self._sessions.append_user_message(session_id, user_text)
        assistant_id = self._sessions.new_message_id()

        await self._notify("chat.begin", {"session_id": session_id, "message_id": assistant_id})

        assistant_text = ""
        history = self._sessions.messages_for_model(session_id)
        for chunk in await asyncio.to_thread(self._provider.collect_stream, history):
            assistant_text += chunk
            await self._notify(
                "chat.delta",
                {"session_id": session_id, "message_id": assistant_id, "delta": chunk},
            )
            await asyncio.sleep(0)

        assistant_item = self._sessions.append_assistant_message(
            session_id,
            assistant_text,
            message_id=assistant_id,
        )

        await self._notify("chat.message", {"session_id": session_id, "message": assistant_item})
        await self._notify("session.updated", {"session_id": session_id, "action": "message"})

        return {"ok": True, "session_id": session_id, "message_id": assistant_id}
