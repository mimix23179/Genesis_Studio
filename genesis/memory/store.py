"""SQLite-backed persistent memory store for Genesis conversations.

Simple, durable, and independent of any provider.
Conversations survive crashes and restarts.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional


class MemoryStore:
    """Stores conversations and messages in a local SQLite database."""

    def __init__(self, db_path: str = "data/genesis.sqlite") -> None:
        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'Untitled',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                session_id TEXT NOT NULL,
                msg_id TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                json TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, created_at);
        """)
        self.conn.commit()

    # ── Sessions ─────────────────────────────────────────────────────

    def create_session(self, session_id: str, title: str = "Untitled") -> None:
        now = int(time.time())
        self.conn.execute(
            "INSERT OR IGNORE INTO sessions(session_id, title, created_at, updated_at) VALUES (?,?,?,?)",
            (session_id, title, now, now),
        )
        self.conn.commit()

    def list_sessions(self) -> List[Dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT session_id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
        )
        return [
            {"id": r[0], "title": r[1], "created_at": r[2], "updated_at": r[3]}
            for r in cur.fetchall()
        ]

    def _ensure_session(self, session_id: str) -> None:
        """Auto-create session if it doesn't exist yet."""
        self.conn.execute(
            "INSERT OR IGNORE INTO sessions(session_id, title, created_at, updated_at) VALUES (?,?,?,?)",
            (session_id, "Untitled", int(time.time()), int(time.time())),
        )

    # ── Messages ─────────────────────────────────────────────────────

    def add_message(self, session_id: str, msg: Dict[str, Any]) -> None:
        self._ensure_session(session_id)
        now = int(time.time())
        self.conn.execute(
            "INSERT OR REPLACE INTO messages(session_id, msg_id, role, created_at, json) VALUES (?,?,?,?,?)",
            (
                session_id,
                msg["id"],
                msg["role"],
                msg.get("created_at", now),
                json.dumps(msg, ensure_ascii=False),
            ),
        )
        # Touch session updated_at
        self.conn.execute(
            "UPDATE sessions SET updated_at=? WHERE session_id=?",
            (now, session_id),
        )
        self.conn.commit()

    def load_session(self, session_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT json FROM messages WHERE session_id=? ORDER BY created_at LIMIT ?",
            (session_id, limit),
        )
        return [json.loads(r[0]) for r in cur.fetchall()]

    def get_session_title(self, session_id: str) -> Optional[str]:
        cur = self.conn.execute(
            "SELECT title FROM sessions WHERE session_id=?", (session_id,)
        )
        row = cur.fetchone()
        return row[0] if row else None

    def rename_session(self, session_id: str, title: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET title=?, updated_at=? WHERE session_id=?",
            (title, int(time.time()), session_id),
        )
        self.conn.commit()

    def delete_session(self, session_id: str) -> None:
        self.conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        self.conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        self.conn.commit()
