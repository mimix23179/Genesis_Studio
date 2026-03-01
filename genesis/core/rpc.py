"""JSON-RPC 2.0 router for Genesis.

Minimal, durable, debuggable. No magic — just a dict of method handlers.
"""

from __future__ import annotations

import traceback
from typing import Any, Awaitable, Callable, Dict, Optional


Handler = Callable[[dict], Awaitable[Any]]


class RpcRouter:
    """Routes incoming JSON-RPC 2.0 messages to registered handlers."""

    def __init__(self) -> None:
        self._methods: Dict[str, Handler] = {}

    def method(self, name: str) -> Callable[[Handler], Handler]:
        """Decorator to register a method handler.

        Usage:
            @router.method("chat.send")
            async def handle_chat_send(params: dict) -> dict:
                ...
        """
        def decorator(fn: Handler) -> Handler:
            self._methods[name] = fn
            return fn
        return decorator

    def register(self, name: str, fn: Handler) -> None:
        """Imperatively register a method handler."""
        self._methods[name] = fn

    def list_methods(self) -> list[str]:
        return sorted(self._methods.keys())

    async def handle(self, msg: dict) -> Optional[dict]:
        """Process one JSON-RPC 2.0 message. Returns response dict or None for notifications."""

        if msg.get("jsonrpc") != "2.0":
            return {
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "error": {"code": -32600, "message": "Invalid JSON-RPC"},
            }

        method_name = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params", {})

        if method_name is None:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32600, "message": "Missing method"},
            }

        fn = self._methods.get(method_name)
        if fn is None:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method_name}"},
            }

        try:
            result = await fn(params)
            if msg_id is None:
                return None  # notification — no response
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except Exception as exc:
            tb = traceback.format_exc()
            if msg_id is None:
                return None
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32000, "message": str(exc), "data": {"traceback": tb}},
            }
