from __future__ import annotations

import secrets
import time
from typing import Any, Callable


class SessionService:
    """In-memory session and message lifecycle service."""

    def __init__(
        self,
        *,
        id_factory: Callable[[str], str] | None = None,
        now_factory: Callable[[], float] | None = None,
    ) -> None:
        self._id_factory = id_factory or self._default_id_factory
        self._now_factory = now_factory or time.time
        self._sessions: dict[str, dict[str, Any]] = {}

    def list_sessions(self) -> list[dict[str, str]]:
        return [
            {"id": sid, "title": str(sess.get("title", "New Conversation"))}
            for sid, sess in sorted(
                self._sessions.items(),
                key=lambda item: item[1].get("updated_at", 0),
                reverse=True,
            )
        ]

    def create_session(self, title: str) -> dict[str, str]:
        session_id = self.new_session_id()
        clean_title = str(title).strip() or "New Conversation"
        now = self._now_factory()
        self._sessions[session_id] = {
            "id": session_id,
            "title": clean_title,
            "messages": [],
            "created_at": now,
            "updated_at": now,
        }
        return {"session_id": session_id, "title": clean_title}

    def open_session(self, session_id: str) -> dict[str, Any]:
        session = self.require_session(session_id)
        return {
            "session_id": session_id,
            "title": str(session.get("title", "New Conversation")),
            "messages": list(session.get("messages", [])),
        }

    def new_session_id(self) -> str:
        return self._id_factory("s")

    def new_message_id(self) -> str:
        return self._id_factory("m")

    def session_count(self) -> int:
        return len(self._sessions)

    def require_session(self, session_id: str) -> dict[str, Any]:
        clean = str(session_id).strip()
        session = self._sessions.get(clean)
        if session is None:
            raise ValueError(f"Session not found: {clean}")
        return session

    def messages_for_model(self, session_id: str) -> list[dict[str, Any]]:
        session = self.require_session(session_id)
        return list(session.get("messages", []))

    def append_user_message(self, session_id: str, text: str) -> dict[str, Any]:
        return self._append_message(session_id, "user", text, message_id=self.new_message_id())

    def append_assistant_message(self, session_id: str, text: str, *, message_id: str) -> dict[str, Any]:
        return self._append_message(session_id, "assistant", text, message_id=message_id)

    def _append_message(self, session_id: str, role: str, text: str, *, message_id: str) -> dict[str, Any]:
        session = self.require_session(session_id)
        item = {
            "id": str(message_id),
            "role": str(role),
            "content": [{"type": "text", "text": str(text)}],
            "created_at": self._now_factory(),
        }
        session["messages"].append(item)
        session["updated_at"] = self._now_factory()
        return item

    @staticmethod
    def _default_id_factory(prefix: str) -> str:
        return f"{prefix}_{secrets.token_hex(6)}"
