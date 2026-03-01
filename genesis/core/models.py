"""Canonical data types for the Genesis protocol.

These types are provider-independent and model-independent.
They define the message format that flows through the entire system.
"""

from __future__ import annotations

import time
import secrets
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


Role = Literal["system", "user", "assistant", "tool"]


def _gen_id(prefix: str = "msg") -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _now() -> int:
    return int(time.time())


class ContentPart(BaseModel):
    """A single piece of message content."""
    type: Literal["text"] = "text"
    text: str


class ChatMessage(BaseModel):
    """A single message in a conversation."""
    id: str = Field(default_factory=lambda: _gen_id("msg"))
    role: Role
    content: List[ContentPart]
    created_at: int = Field(default_factory=_now)
    tool: Optional[Dict[str, Any]] = None
    meta: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def user(cls, text: str) -> "ChatMessage":
        return cls(role="user", content=[ContentPart(text=text)])

    @classmethod
    def assistant(cls, text: str, **meta: Any) -> "ChatMessage":
        return cls(role="assistant", content=[ContentPart(text=text)], meta=meta)

    @classmethod
    def system(cls, text: str) -> "ChatMessage":
        return cls(role="system", content=[ContentPart(text=text)])

    def text(self) -> str:
        """Return concatenated text content."""
        return "".join(p.text for p in self.content if p.type == "text")


class ToolCall(BaseModel):
    """A request from the brain to execute a tool."""
    id: str = Field(default_factory=lambda: _gen_id("call"))
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    timeout_ms: int = 20_000


class ToolResult(BaseModel):
    """The result of executing a tool."""
    id: str
    ok: bool
    result: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
