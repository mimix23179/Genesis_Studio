from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Any, Callable


class SessionService:
    """In-memory session and message lifecycle service."""

    def __init__(
        self,
        *,
        id_factory: Callable[[str], str] | None = None,
        now_factory: Callable[[], float] | None = None,
        storage_path: str | Path | None = None,
    ) -> None:
        self._id_factory = id_factory or self._default_id_factory
        self._now_factory = now_factory or time.time
        self._sessions: dict[str, dict[str, Any]] = {}
        self._storage_path = Path(storage_path).expanduser() if storage_path else None
        self._load()

    def list_sessions(self) -> list[dict[str, str]]:
        return [
            {
                "id": sid,
                "title": str(sess.get("title", "New Conversation")),
                "preview": self._message_preview(sess),
                "message_count": str(len(sess.get("messages", []))),
                "updated_at": str(sess.get("updated_at", 0)),
                "active_model": str(sess.get("active_model", "") or ""),
            }
            for sid, sess in sorted(
                self._sessions.items(),
                key=lambda item: item[1].get("updated_at", 0),
                reverse=True,
            )
        ]

    def create_session(self, title: str, *, active_model: str | None = None) -> dict[str, str]:
        session_id = self.new_session_id()
        clean_title = str(title).strip() or "New Conversation"
        now = self._now_factory()
        self._sessions[session_id] = {
            "id": session_id,
            "title": clean_title,
            "messages": [],
            "created_at": now,
            "updated_at": now,
            "active_model": str(active_model or "").strip() or None,
        }
        self._save()
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

    def rename_session(self, session_id: str, title: str) -> dict[str, Any]:
        session = self.require_session(session_id)
        cleaned = str(title or "").strip()
        if cleaned:
            session["title"] = cleaned
            session["updated_at"] = self._now_factory()
            self._save()
        return {"session_id": session_id, "title": str(session.get("title", "New Conversation"))}

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
        self._save()
        return item

    def _message_preview(self, session: dict[str, Any]) -> str:
        messages = session.get("messages", [])
        if not isinstance(messages, list) or not messages:
            return "New conversation"
        last = messages[-1] if isinstance(messages[-1], dict) else {}
        content = last.get("content", [])
        if isinstance(content, list):
            text = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict)).strip()
        else:
            text = str(content or "").strip()
        compact = " ".join(text.split())
        return compact[:88] if compact else "New conversation"

    def _load(self) -> None:
        if self._storage_path is None or not self._storage_path.exists():
            return
        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except Exception:
            return
        sessions = payload.get("sessions", []) if isinstance(payload, dict) else []
        if not isinstance(sessions, list):
            return
        for item in sessions:
            if not isinstance(item, dict):
                continue
            session_id = str(item.get("id", "")).strip()
            if not session_id:
                continue
            self._sessions[session_id] = {
                "id": session_id,
                "title": str(item.get("title", "New Conversation")) or "New Conversation",
                "messages": list(item.get("messages", [])) if isinstance(item.get("messages", []), list) else [],
                "created_at": float(item.get("created_at", self._now_factory())),
                "updated_at": float(item.get("updated_at", self._now_factory())),
                "active_model": str(item.get("active_model", "") or "") or None,
            }

    def _save(self) -> None:
        if self._storage_path is None:
            return
        payload = {
            "sessions": [
                {
                    "id": session_id,
                    "title": str(session.get("title", "New Conversation")),
                    "messages": list(session.get("messages", [])),
                    "created_at": float(session.get("created_at", self._now_factory())),
                    "updated_at": float(session.get("updated_at", self._now_factory())),
                    "active_model": session.get("active_model"),
                }
                for session_id, session in self._sessions.items()
            ]
        }
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            self._storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _default_id_factory(prefix: str) -> str:
        return f"{prefix}_{secrets.token_hex(6)}"
