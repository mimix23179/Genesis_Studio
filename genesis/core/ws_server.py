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
from ..openml import (
    AbyssStore,
    OpenMLState,
    load_runtime_jadepack,
    openml_step as openml_decide,
    prepare_bonzai_handoff,
)

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
        self.openml_data_root = Path("data/openml")
        self.openml_store = AbyssStore(self.openml_data_root)
        self.openml_workspace_id: str | None = None
        self.openml_runtime_config: Dict[str, Any] = {}
        self.openml_runtime_rules: Dict[str, Any] = {}

        # Wire everything up
        self._register_tools()
        self._init_brain()
        self._init_openml()
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

    def _init_openml(self) -> None:
        """Initialize OpenML runtime config/rules and workspace mapping."""
        try:
            runtime_payload = load_runtime_jadepack(
                data_root=self.openml_data_root,
                auto_create=True,
            )
            self.openml_runtime_config = runtime_payload.get("config", {})
            self.openml_runtime_rules = runtime_payload.get("rules", {})
        except Exception as exc:
            logger.warning("OpenML runtime pack initialization failed: %s", exc)
            self.openml_runtime_config = {}
            self.openml_runtime_rules = {}

        self._sync_openml_workspace(self.workspace_root)

    def _sync_openml_workspace(self, root: str) -> str | None:
        try:
            self.openml_workspace_id = self.openml_store.create_workspace(root)
            self.openml_store.ingest_workspace(self.openml_workspace_id)
            return self.openml_workspace_id
        except Exception as exc:
            logger.warning("OpenML workspace sync failed for %s: %s", root, exc)
            self.openml_workspace_id = None
            return None

    def _message_text(self, message: dict[str, Any]) -> str:
        content = message.get("content", [])
        if isinstance(content, list):
            return "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        return ""

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
            self._sync_openml_workspace(self.workspace_root)
            await self._broadcast_notification(
                "log.append", {"line": f"Workspace set: {self.workspace_root}"}
            )
            return {"ok": True}

        @self.router.method("openml.status")
        async def _openml_status(params: dict) -> dict:
            integrity = self.openml_store.run_integrity_checks(verify_blob_hashes=False)
            return {
                "workspace_id": self.openml_workspace_id,
                "schema_version": self.openml_store.get_schema_version(),
                "runtime_rules_loaded": bool(self.openml_runtime_rules),
                "runtime_config_loaded": bool(self.openml_runtime_config),
                "integrity": integrity,
            }

        @self.router.method("openml.dataset.export")
        async def _openml_dataset_export(params: dict) -> dict:
            workspace_id = params.get("workspace_id") or self.openml_workspace_id
            if not workspace_id:
                raise ValueError("OpenML workspace is not initialized")

            result = prepare_bonzai_handoff(
                store=self.openml_store,
                workspace_id=str(workspace_id),
                limit_traces=int(params.get("limit_traces", 200)),
                output_dir=params.get("output_dir", "data/openml/datasets"),
                include_csv=bool(params.get("include_csv", True)),
                min_rows=int(params.get("min_rows", 10)),
                success_threshold=float(params.get("success_threshold", 0.6)),
                feature_version=str(params.get("feature_version", "1")),
                timestamp=params.get("timestamp"),
            )

            return {
                "handoff_ready": bool(result.get("handoff_ready", False)),
                "evaluation": result.get("evaluation", {}),
                "exports": result.get("exports", {}),
                "row_count": len(result.get("rows", [])),
            }

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

            trace_id: str | None = None
            decision = None
            user_text = self._message_text(user_msg)

            try:
                if self.openml_workspace_id is None:
                    self._sync_openml_workspace(self.workspace_root)

                if self.openml_workspace_id is not None:
                    recent_traces = self.openml_store.list_recent_traces(
                        self.openml_workspace_id,
                        limit=20,
                    )
                    trace_id = self.openml_store.start_trace(
                        session_id,
                        self.openml_workspace_id,
                        summary=(user_text[:160] or "chat.send"),
                    )

                    decision = openml_decide(
                        OpenMLState(
                            user_message=user_text,
                            workspace_id=self.openml_workspace_id,
                            session_id=session_id,
                            available_tools=self.tools.list(),
                            recent_traces=recent_traces,
                            metadata={
                                "has_git": (Path(self.workspace_root) / ".git").exists(),
                                "dirty_repo": False,
                            },
                        ),
                        store=self.openml_store,
                        trace_id=trace_id,
                    )

                if decision is not None and decision.action_type == "tool" and decision.tool in self.tools.list():
                    start_ms = int(time.time() * 1000)
                    await self._broadcast_notification(
                        "tool.call",
                        {
                            "id": _gen_id("call"),
                            "tool": decision.tool,
                            "args": decision.args,
                            "timeout_ms": 20_000,
                        },
                    )

                    tool_ok = False
                    tool_payload: dict[str, Any] = {}
                    tool_error: str | None = None
                    try:
                        fn = self.tools.get(decision.tool)
                        tool_payload = await fn(decision.args)
                        tool_ok = True
                    except Exception as exc:
                        tool_ok = False
                        tool_payload = {}
                        tool_error = str(exc)

                    duration_ms = int(time.time() * 1000) - start_ms
                    await self._broadcast_notification(
                        "tool.result",
                        {
                            "ok": tool_ok,
                            "result": tool_payload,
                            "error": tool_error,
                            "duration_ms": duration_ms,
                            "tool": decision.tool,
                        },
                    )
                    if trace_id is not None:
                        self.openml_store.append_trace_event(
                            trace_id,
                            "tool.call",
                            {"tool": decision.tool, "args": decision.args, "started_ms": start_ms},
                        )
                        self.openml_store.append_trace_event(
                            trace_id,
                            "tool.result",
                            {
                                "tool": decision.tool,
                                "ok": tool_ok,
                                "error": tool_error,
                                "result": tool_payload,
                                "duration_ms": duration_ms,
                            },
                        )

                if decision is not None and decision.action_type == "ask_user" and decision.question:
                    final_text = decision.question
                elif decision is not None and decision.action_type == "final_answer" and decision.final_answer:
                    final_text = decision.final_answer
                else:
                    context = self.memory.load_session(session_id, limit=200)
                    acc: list[str] = []
                    async for chunk in self.brain.stream_reply(context):
                        acc.append(chunk)
                        await self._broadcast_notification("chat.delta", {
                            "session_id": session_id,
                            "message_id": assistant_id,
                            "delta": chunk,
                        })
                        await asyncio.sleep(0)
                    final_text = "".join(acc)
            except Exception as exc:
                if trace_id is not None:
                    try:
                        self.openml_store.finish_trace(
                            trace_id,
                            status="error",
                            metrics={"error_type": type(exc).__name__},
                        )
                        self.openml_store.record_outcome(
                            trace_id,
                            success=False,
                            error_type=type(exc).__name__,
                            error_summary=str(exc),
                            data={"source": "chat.send"},
                        )
                    except Exception:
                        pass
                raise

            assistant_msg = {
                "id": assistant_id,
                "role": "assistant",
                "created_at": _now(),
                "content": [{"type": "text", "text": final_text}],
                "meta": {
                    "brain": type(self.brain).__name__,
                    "openml": {
                        "action_type": getattr(decision, "action_type", None),
                        "tool": getattr(decision, "tool", None),
                    },
                },
            }
            self.memory.add_message(session_id, assistant_msg)
            await self._broadcast_notification("session.updated", {"session_id": session_id})

            if trace_id is not None:
                self.openml_store.finish_trace(
                    trace_id,
                    status="ok",
                    metrics={
                        "chosen_tool": getattr(decision, "tool", ""),
                        "action_type": getattr(decision, "action_type", ""),
                    },
                )
                self.openml_store.record_outcome(
                    trace_id,
                    success=True,
                    data={"assistant_message_id": assistant_id},
                )

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
