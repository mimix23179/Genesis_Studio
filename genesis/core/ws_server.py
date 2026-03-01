"""Genesis Runtime — WebSocket server hosting the soul.

Starts a JSON-RPC 2.0 WebSocket server that:
  - accepts chat messages
  - streams per-character deltas back
  - persists conversations to SQLite
  - dispatches tools deterministically
  - works with or without a model loaded
"""

from __future__ import annotations

import asyncio
import json
import time
import secrets
import logging
from pathlib import Path
from typing import Any, Dict, Set

import websockets
from websockets.server import WebSocketServerProtocol

from .rpc import RpcRouter
from .models import _gen_id, _now
from ..memory.store import MemoryStore
from ..brain.adapter_base import Brain
from ..brain.fallback_rules import FallbackRulesBrain
from ..brain.local_llama import LocalLlamaBrain
from ..tools.registry import ToolRegistry
from ..tools.fs_tools import fs_read, fs_write, fs_list, fs_mkdir, fs_delete

logger = logging.getLogger("genesis.runtime")


class GenesisRuntime:
    """The 'soul' of Genesis — a deterministic runtime that can operate
    even if the model is swapped out or offline.

    The soul is:
      - a stable message bus (JSON-RPC over WebSocket)
      - a stable tool calling contract
      - a stable memory store
      - a replaceable 'brain' (local LLM or fallback rules)
    """

    def __init__(
        self,
        db_path: str = "data/genesis.sqlite",
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        self.host = host
        self.port = port

        # Core components
        self.router = RpcRouter()
        self.memory = MemoryStore(db_path)
        self.tools = ToolRegistry()
        self.brain: Brain = FallbackRulesBrain()

        # Connected clients
        self._clients: Set[WebSocketServerProtocol] = set()

        # State
        self.workspace_root = "."
        self.ui_state: Dict[str, Any] = {}

        # Wire everything up
        self._register_tools()
        self._init_brain()
        self._register_methods()

    def _init_brain(self) -> None:
        """Auto-select a local brain when a GGUF model is present."""
        model_dir = Path("models")
        if not model_dir.exists():
            return

        ggufs = sorted(model_dir.glob("*.gguf"))
        if not ggufs:
            return

        candidate = ggufs[0]
        try:
            self.brain = LocalLlamaBrain(model_path=str(candidate))
            logger.info("Local brain active: %s", candidate)
        except Exception as exc:
            logger.warning("Falling back to rules brain: %s", exc)

    # ── Tool Registration ────────────────────────────────────────────

    def _register_tools(self) -> None:
        self.tools.register("fs.read", fs_read)
        self.tools.register("fs.write", fs_write)
        self.tools.register("fs.list", fs_list)
        self.tools.register("fs.mkdir", fs_mkdir)
        self.tools.register("fs.delete", fs_delete)

    # ── RPC Method Registration ──────────────────────────────────────

    def _register_methods(self) -> None:

        @self.router.method("workspace.set")
        async def _workspace_set(params: dict) -> dict:
            self.workspace_root = params.get("root", ".")
            await self._broadcast_notification(
                "log.append", {"line": f"Workspace set: {self.workspace_root}"}
            )
            return {"ok": True}

        @self.router.method("runtime.info")
        async def _runtime_info(params: dict) -> dict:
            return {
                "workspace_root": self.workspace_root,
                "brain": self.brain.name(),
                "tools": self.tools.list(),
            }

        @self.router.method("tool.list")
        async def _tool_list(params: dict) -> dict:
            return {"tools": self.tools.describe()}

        @self.router.method("session.list")
        async def _session_list(params: dict) -> dict:
            sessions = self.memory.list_sessions()
            return {"sessions": sessions}

        @self.router.method("session.open")
        async def _session_open(params: dict) -> dict:
            sid = params["session_id"]
            msgs = self.memory.load_session(sid)
            title = self.memory.get_session_title(sid) or "Untitled"
            return {"session_id": sid, "title": title, "messages": msgs}

        @self.router.method("session.create")
        async def _session_create(params: dict) -> dict:
            title = params.get("title", "New Conversation")
            sid = _gen_id("sess")
            self.memory.create_session(sid, title)
            await self._broadcast_notification("session.updated", {})
            return {"session_id": sid, "title": title}

        @self.router.method("chat.send")
        async def _chat_send(params: dict) -> dict:
            session_id = params["session_id"]
            user_msg = params["message"]

            # Ensure user message has an ID and timestamp
            if "id" not in user_msg:
                user_msg["id"] = _gen_id("msg")
            user_msg.setdefault("created_at", _now())
            user_msg.setdefault("role", "user")

            # Persist user message
            self.memory.add_message(session_id, user_msg)
            await self._broadcast_notification("session.updated", {"session_id": session_id})

            # Create assistant message ID
            assistant_id = _gen_id("msg")

            # Notify clients that streaming has begun
            await self._broadcast_notification("chat.begin", {
                "session_id": session_id,
                "message_id": assistant_id,
            })

            # Load conversation context
            context = self.memory.load_session(session_id, limit=200)

            # Stream per-character from the brain
            acc: list[str] = []
            async for chunk in self.brain.stream_reply(context):
                acc.append(chunk)
                await self._broadcast_notification("chat.delta", {
                    "session_id": session_id,
                    "message_id": assistant_id,
                    "delta": chunk,
                })
                # Small yield to allow UI refresh
                await asyncio.sleep(0)

            # Finalize
            final_text = "".join(acc)
            assistant_msg = {
                "id": assistant_id,
                "role": "assistant",
                "created_at": _now(),
                "content": [{"type": "text", "text": final_text}],
                "meta": {"brain": type(self.brain).__name__},
            }
            self.memory.add_message(session_id, assistant_msg)
            await self._broadcast_notification("session.updated", {"session_id": session_id})

            await self._broadcast_notification("chat.message", {
                "session_id": session_id,
                "message": assistant_msg,
            })

            return {"ok": True, "assistant_message_id": assistant_id}

        @self.router.method("tool.call")
        async def _tool_call(params: dict) -> dict:
            call_id = params.get("id", _gen_id("call"))
            tool_name = params["tool"]
            args = params.get("args", {})

            await self._broadcast_notification("tool.call", {
                "id": call_id,
                "tool": tool_name,
                "args": args,
                "timeout_ms": params.get("timeout_ms", 20_000),
            })

            try:
                fn = self.tools.get(tool_name)
                call_result = await fn(args)
                payload = {
                    "id": call_id,
                    "ok": True,
                    "result": call_result,
                    "error": None,
                }
                await self._broadcast_notification("tool.result", payload)
                return payload
            except KeyError:
                payload = {
                    "id": call_id,
                    "ok": False,
                    "result": {},
                    "error": f"Unknown tool: {tool_name}",
                }
                await self._broadcast_notification("tool.result", payload)
                return payload
            except Exception as exc:
                payload = {
                    "id": call_id,
                    "ok": False,
                    "result": {},
                    "error": str(exc),
                }
                await self._broadcast_notification("tool.result", payload)
                return payload

        @self.router.method("tool.execute")
        async def _tool_execute(params: dict) -> dict:
            # Backward-compat alias
            result = await _tool_call(params)
            return result

        @self.router.method("tool.result")
        async def _tool_result(params: dict) -> dict:
            # Accepted for compatibility when a client executes tools.
            await self._broadcast_notification("tool.result", params)
            return {"ok": True}

        @self.router.method("ui.event")
        async def _ui_event(params: dict) -> dict:
            event_type = params.get("type", "unknown")
            event_payload = params.get("payload", {})
            self.ui_state[event_type] = {
                "at": _now(),
                "payload": event_payload,
            }
            await self._broadcast_notification("trace.event", {
                "source": "ui",
                "type": event_type,
                "payload": event_payload,
                "created_at": _now(),
            })
            return {"ok": True}

    # ── Broadcasting ─────────────────────────────────────────────────

    async def _broadcast_notification(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no id) to all connected clients."""
        payload = json.dumps(
            {"jsonrpc": "2.0", "method": method, "params": params},
            ensure_ascii=False,
        )
        dead: list[WebSocketServerProtocol] = []
        for ws in self._clients:
            try:
                await ws.send(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    # ── WebSocket Handler ────────────────────────────────────────────

    async def _ws_handler(self, ws: WebSocketServerProtocol) -> None:
        self._clients.add(ws)
        logger.info("Client connected (%d total)", len(self._clients))
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    }))
                    continue

                resp = await self.router.handle(msg)
                if resp is not None:
                    await ws.send(json.dumps(resp, ensure_ascii=False))
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)
            logger.info("Client disconnected (%d remaining)", len(self._clients))

    # ── Lifecycle ────────────────────────────────────────────────────

    async def serve_async(self) -> None:
        """Start the WebSocket server (blocks forever)."""
        logger.info("Genesis Runtime starting on ws://%s:%d", self.host, self.port)
        async with websockets.serve(self._ws_handler, self.host, self.port):
            await asyncio.Future()  # run forever

    def serve(self) -> None:
        """Blocking convenience wrapper."""
        asyncio.run(self.serve_async())

    def set_brain(self, brain: Brain) -> None:
        """Swap the brain at runtime."""
        old = type(self.brain).__name__
        self.brain = brain
        logger.info("Brain swapped: %s -> %s", old, type(brain).__name__)


def main() -> None:
    """Standalone entry point for the runtime."""
    logging.basicConfig(level=logging.INFO, format="[Genesis] %(message)s")
    rt = GenesisRuntime()
    rt.serve()


if __name__ == "__main__":
    main()
