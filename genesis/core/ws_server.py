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
from enum import Enum
from typing import Any, AsyncIterator, Dict, Set

import websockets
from websockets.server import WebSocketServerProtocol

from .rpc import RpcRouter
from .models import _gen_id, _now
from ..memory.store import MemoryStore
from ..tools.registry import ToolRegistry
from ..tools.fs_tools import fs_read, fs_write, fs_list, fs_mkdir, fs_delete
from ..openml import (
    AbyssStore,
    OpenMLState,
    load_runtime_jadepack,
    openml_step as openml_decide,
    prepare_bonzai_handoff,
)
from ..brain import SakuraBrain
from ..openml.sakura import ChatMsg, ChatPrompt, GenParams, SakuraRuntimeConfig
from ..openml.sakura.generate.stops import apply_turn_stop

logger = logging.getLogger("genesis.runtime")


class RuntimeState(Enum):
    BOOTING = "BOOTING"
    READY = "READY"
    SESSION_PENDING = "SESSION_PENDING"
    STREAMING = "STREAMING"
    TOOL_WAIT = "TOOL_WAIT"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"


class GenesisRuntime:
    """The 'soul' of Genesis — a deterministic runtime that can operate
    even if the model is swapped out or offline.

    The soul is:
      - a stable message bus (JSON-RPC over WebSocket)
      - a stable tool calling contract
      - a stable memory store
            - a Sakura-first local inference engine with degraded fallback
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
        self.sakura_config = SakuraRuntimeConfig()
        self.sakura_engine = SakuraBrain(config=self.sakura_config)
        self.runtime_state = RuntimeState.BOOTING.value
        self.runtime_state_reason = "runtime_initializing"
        self.runtime_state_updated_at = _now()
        self._workspace_sync_task: asyncio.Task | None = None

        # Wire everything up
        self._register_tools()
        self._init_openml()
        self._register_methods()
        self._set_runtime_state_sync(
            self._resolve_initial_runtime_state(),
            "runtime_initialized",
        )

    def _resolve_initial_runtime_state(self) -> RuntimeState:
        if self.openml_workspace_id is None:
            return RuntimeState.DEGRADED
        if self._is_sakura_enabled() and not self.sakura_engine.is_loaded:
            return RuntimeState.DEGRADED
        # 2C-7.2: missing context index → DEGRADED (chat still works)
        if self._is_context_enabled() and not self.sakura_engine.context_ready:
            return RuntimeState.DEGRADED
        return RuntimeState.READY

    def _runtime_state_snapshot(self) -> dict[str, Any]:
        return {
            "state": self.runtime_state,
            "reason": self.runtime_state_reason,
            "updated_at": self.runtime_state_updated_at,
            "workspace_ready": bool(self.openml_workspace_id),
            "sakura_enabled": self._is_sakura_enabled(),
            "sakura_loaded": self.sakura_engine.is_loaded,
            "context_enabled": self.sakura_config.context_enabled,
            "context_ready": self.sakura_engine.context_ready,
        }

    def _is_sakura_enabled(self) -> bool:
        sakura_cfg = self.openml_runtime_config.get("sakura", {})
        if isinstance(sakura_cfg, dict):
            if "enabled" in sakura_cfg:
                return bool(sakura_cfg.get("enabled"))
        if "sakura_enabled" in self.openml_runtime_config:
            return bool(self.openml_runtime_config.get("sakura_enabled", False))

        # Fallback: auto-enable if a known Sakura pack exists.
        fallback_candidates = [
            self.openml_data_root / "jade" / "sakura_v1.jadepack",
            self.openml_data_root / "jade" / "s1_full.jadepack",
            self.openml_data_root / "jade" / "sakura_test.jadepack",
        ]
        return any(path.exists() for path in fallback_candidates)

    def _sakura_jadepack_path(self) -> str:
        sakura_cfg = self.openml_runtime_config.get("sakura", {})
        if isinstance(sakura_cfg, dict):
            value = sakura_cfg.get("jadepack_path")
            if isinstance(value, str) and value.strip():
                return value.strip()
        value = self.openml_runtime_config.get("sakura_jadepack_path", "")
        if value:
            return str(value).strip()

        fallback_candidates = [
            self.openml_data_root / "jade" / "sakura_v1.jadepack",
            self.openml_data_root / "jade" / "s1_full.jadepack",
            self.openml_data_root / "jade" / "sakura_test.jadepack",
        ]
        for path in fallback_candidates:
            if path.exists():
                return str(path).replace("\\", "/")
        return ""

    def _is_context_enabled(self) -> bool:
        """2C-7.1: Check if context toggle is ON."""
        sakura_cfg = self.openml_runtime_config.get("sakura", {})
        if isinstance(sakura_cfg, dict):
            return bool(sakura_cfg.get("context_enabled", True))
        return True

    def _build_context_index(self) -> None:
        """2C-7: Build context index from workspace documents."""
        if self.openml_workspace_id is None:
            return
        try:
            docs = self.openml_store.list_documents(self.openml_workspace_id)
            if not docs:
                return

            root = Path(self.workspace_root).resolve()
            documents: list[dict[str, str]] = []
            for doc in docs:
                doc_path = root / doc["path"]
                if not doc_path.exists():
                    continue
                # Only index text-like files
                mime = doc.get("mime") or ""
                ext = doc_path.suffix.lower()
                if ext in {".pyc", ".whl", ".bin", ".sqlite", ".blob", ".png", ".jpg", ".ico"}:
                    continue
                try:
                    text = doc_path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                if text.strip():
                    documents.append({"path": doc["path"], "text": text})

            if not documents:
                return

            stats = self.sakura_engine.build_context_index(documents)
            logger.info(
                "Context index built: %d chunks from %d docs (hash=%s)",
                stats["chunk_count"], stats["doc_count"], stats["index_hash"][:12],
            )

            # Store chunks to Abyss (2C-1.1)
            chunk_dicts = []
            for cid, chunk in self.sakura_engine._chunks.items():
                chunk_dicts.append({
                    "chunk_id": chunk.chunk_id,
                    "path": chunk.path,
                    "chunk_index": chunk.chunk_index,
                    "total_chunks": chunk.total_chunks,
                    "offset_start": chunk.offset_start,
                    "offset_end": chunk.offset_end,
                    "sha256": chunk.sha256,
                    "text": chunk.text,
                    "tags": chunk.tags,
                })
            self.openml_store.delete_chunks(self.openml_workspace_id)
            stored = self.openml_store.store_chunks(self.openml_workspace_id, chunk_dicts)
            logger.info("Stored %d chunks to Abyss", stored)
        except Exception as exc:
            logger.warning("Context index build failed: %s", exc)

    def _init_sakura(self) -> None:
        enabled = self._is_sakura_enabled()
        jadepack_path = self._sakura_jadepack_path()
        context_enabled = self._is_context_enabled()

        sakura_cfg = self.openml_runtime_config.get("sakura", {})
        if not isinstance(sakura_cfg, dict):
            sakura_cfg = {}
        decode_cfg = sakura_cfg.get("decode", {}) if isinstance(sakura_cfg.get("decode", {}), dict) else {}

        self.sakura_config = SakuraRuntimeConfig(
            enabled=enabled,
            jadepack_path=jadepack_path,
            context_enabled=context_enabled,
            max_context_chars=int(sakura_cfg.get("max_context_chars", 24_000)),
            max_context_files=int(sakura_cfg.get("max_context_files", 12)),
            max_chunks_per_file=int(sakura_cfg.get("max_chunks_per_file", 6)),
            retrieval_top_k=int(sakura_cfg.get("retrieval_top_k", 10)),
            prompt_reserved_tokens=int(sakura_cfg.get("prompt_reserved_tokens", 160)),
            default_max_new_tokens=int(decode_cfg.get("max_new_tokens", 320)),
            default_temperature=float(decode_cfg.get("temperature", 0.78)),
            default_top_k=int(decode_cfg.get("top_k", 60)),
            default_top_p=float(decode_cfg.get("top_p", 0.92)),
            default_repetition_penalty=float(decode_cfg.get("repetition_penalty", 1.2)),
            default_no_repeat_ngram_size=int(decode_cfg.get("no_repeat_ngram_size", 4)),
        )
        self.sakura_engine = SakuraBrain(config=self.sakura_config)

        if not enabled:
            return

        if not jadepack_path:
            logger.warning("Sakura enabled but jadepack path is not configured")
            return

        try:
            self.sakura_engine.load_from_jadepack(jadepack_path)
            logger.info("Sakura engine loaded from jadepack: %s", jadepack_path)
        except Exception as exc:
            logger.warning("Sakura engine failed to load from jadepack %s: %s", jadepack_path, exc)

        # 2C-7: build context index after sakura init
        if context_enabled:
            self._build_context_index()

    def _set_runtime_state_sync(self, state: RuntimeState | str, reason: str) -> None:
        next_state = state.value if isinstance(state, RuntimeState) else str(state)
        prev_state = self.runtime_state
        self.runtime_state = next_state
        self.runtime_state_reason = reason
        self.runtime_state_updated_at = _now()
        if prev_state != next_state:
            logger.info("Runtime state: %s -> %s (%s)", prev_state, next_state, reason)

    async def _set_runtime_state(self, state: RuntimeState | str, reason: str) -> None:
        next_state = state.value if isinstance(state, RuntimeState) else str(state)
        prev_state = self.runtime_state
        self.runtime_state = next_state
        self.runtime_state_reason = reason
        self.runtime_state_updated_at = _now()

        if prev_state != next_state:
            logger.info("Runtime state: %s -> %s (%s)", prev_state, next_state, reason)

        payload = {
            **self._runtime_state_snapshot(),
            "previous_state": prev_state,
        }
        await self._broadcast_notification("runtime.state", payload)
        await self._broadcast_notification(
            "trace.event",
            {
                "source": "runtime",
                "type": "runtime.state_changed",
                "payload": payload,
                "created_at": _now(),
            },
        )

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

        self._init_sakura()

    def _schedule_workspace_sync(self, root: str, reason: str = "workspace_sync_scheduled") -> None:
        if self._workspace_sync_task is not None and not self._workspace_sync_task.done():
            return

        async def _runner() -> None:
            await self._set_runtime_state(RuntimeState.BOOTING, reason)
            workspace_id = await asyncio.to_thread(self._sync_openml_workspace, root)
            if workspace_id is None:
                await self._set_runtime_state(RuntimeState.DEGRADED, "workspace_sync_failed")
            else:
                await self._set_runtime_state(RuntimeState.READY, "workspace_synced")

        self._workspace_sync_task = asyncio.create_task(_runner())

    def _sync_openml_workspace(self, root: str) -> str | None:
        try:
            self.openml_workspace_id = self.openml_store.create_workspace(root)
            self.openml_store.ingest_workspace(self.openml_workspace_id)
            if self.sakura_engine.is_loaded and self._is_context_enabled():
                self._build_context_index()
            self._set_runtime_state_sync(RuntimeState.READY, "workspace_synced")
            return self.openml_workspace_id
        except Exception as exc:
            logger.warning("OpenML workspace sync failed for %s: %s", root, exc)
            self.openml_workspace_id = None
            self._set_runtime_state_sync(RuntimeState.DEGRADED, "workspace_sync_failed")
            return None

    def _message_text(self, message: dict[str, Any]) -> str:
        content = message.get("content", [])
        if isinstance(content, list):
            return "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        return ""

    async def _stream_degraded_reply(self, user_text: str) -> AsyncIterator[str]:
        text = (
            "Sakura is currently unavailable, so Genesis is running in degraded mode. "
            "I can still preserve sessions and tool calls while you verify the jadepack.\n\n"
            f"Last prompt summary: {user_text[:180] or 'empty prompt'}"
        )
        for ch in text:
            yield ch
            await asyncio.sleep(0)

    def _decision_rule_name(self, decision: Any) -> str:
        evidence = getattr(decision, "evidence", None)
        if not isinstance(evidence, list):
            return ""
        for item in evidence:
            if not isinstance(item, dict):
                continue
            if item.get("source") == "bonzai.rule":
                value = item.get("rule")
                if isinstance(value, str):
                    return value
        return ""

    def _should_short_circuit_ask_user(self, decision: Any) -> bool:
        if decision is None or getattr(decision, "action_type", "") != "ask_user":
            return False
        if self._is_sakura_enabled() and self.sakura_engine.is_loaded:
            return False
        confidence = float(getattr(decision, "confidence", 0.0) or 0.0)
        rule_name = self._decision_rule_name(decision)
        if rule_name in {"workspace-missing", "repeated-failure"}:
            return True
        return confidence >= 0.85

    def _resolve_gen_params(self, user_text: str) -> GenParams:
        sakura_cfg = self.openml_runtime_config.get("sakura", {})
        decode_cfg = sakura_cfg.get("decode", {}) if isinstance(sakura_cfg, dict) else {}

        seed_cfg = decode_cfg.get("seed") if isinstance(decode_cfg, dict) else None
        if isinstance(seed_cfg, int) and seed_cfg > 0:
            seed_value = seed_cfg
        else:
            seed_value = int(time.time() * 1000) ^ secrets.randbits(16)

        max_new_tokens = int(decode_cfg.get("max_new_tokens", self.sakura_config.default_max_new_tokens)) if isinstance(decode_cfg, dict) else int(self.sakura_config.default_max_new_tokens)
        temperature = float(decode_cfg.get("temperature", self.sakura_config.default_temperature)) if isinstance(decode_cfg, dict) else float(self.sakura_config.default_temperature)
        top_k = int(decode_cfg.get("top_k", self.sakura_config.default_top_k)) if isinstance(decode_cfg, dict) else int(self.sakura_config.default_top_k)
        top_p = float(decode_cfg.get("top_p", self.sakura_config.default_top_p)) if isinstance(decode_cfg, dict) else float(self.sakura_config.default_top_p)
        repetition_penalty = float(decode_cfg.get("repetition_penalty", self.sakura_config.default_repetition_penalty)) if isinstance(decode_cfg, dict) else float(self.sakura_config.default_repetition_penalty)
        no_repeat_ngram_size = int(decode_cfg.get("no_repeat_ngram_size", self.sakura_config.default_no_repeat_ngram_size)) if isinstance(decode_cfg, dict) else int(self.sakura_config.default_no_repeat_ngram_size)

        if len(user_text) < 24:
            max_new_tokens = max(120, min(max_new_tokens, 220))

        return GenParams(
            max_new_tokens=max(64, min(1024, max_new_tokens)),
            temperature=max(0.2, min(1.2, temperature)),
            top_k=max(1, min(200, top_k)),
            top_p=max(0.5, min(1.0, top_p)),
            repetition_penalty=max(1.0, min(2.0, repetition_penalty)),
            no_repeat_ngram_size=max(2, min(8, no_repeat_ngram_size)),
            seed=int(seed_value),
        )

    def _text_quality_metrics(self, text: str) -> dict[str, float | int]:
        cleaned = " ".join((text or "").split())
        if not cleaned:
            return {
                "chars": 0,
                "tokens_approx": 0,
                "distinct_1": 0.0,
                "distinct_2": 0.0,
                "line_repeat_ratio": 0.0,
            }

        tokens = cleaned.lower().split()
        unigrams = set(tokens)
        bigrams = set(zip(tokens, tokens[1:])) if len(tokens) > 1 else set()
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if lines:
            line_repeat_ratio = 1.0 - (len(set(lines)) / len(lines))
        else:
            line_repeat_ratio = 0.0

        return {
            "chars": len(cleaned),
            "tokens_approx": len(tokens),
            "distinct_1": round(len(unigrams) / max(1, len(tokens)), 4),
            "distinct_2": round(len(bigrams) / max(1, len(tokens) - 1), 4),
            "line_repeat_ratio": round(line_repeat_ratio, 4),
        }

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
            self._schedule_workspace_sync(self.workspace_root, reason="workspace_set")
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
                "runtime_state": self._runtime_state_snapshot(),
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
            brain_name = self.sakura_engine.name if self.sakura_engine.is_loaded else "DegradedFallback"
            return {
                "workspace_root": self.workspace_root,
                "brain": brain_name,
                "tools": self.tools.list(),
                "sakura": {
                    "enabled": self._is_sakura_enabled(),
                    "loaded": self.sakura_engine.is_loaded,
                    "jadepack_path": self.sakura_config.jadepack_path,                    "context_enabled": self.sakura_config.context_enabled,
                    "context_ready": self.sakura_engine.context_ready,                },
                "runtime_state": self._runtime_state_snapshot(),
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
            if not params.get("session_id"):
                await self._set_runtime_state(RuntimeState.SESSION_PENDING, "chat_send_missing_session")
                raise ValueError("session_id is required")

            session_id = params["session_id"]
            user_msg = params["message"]
            await self._set_runtime_state(RuntimeState.STREAMING, "chat_send_started")

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
            system_prompt = params.get("system_prompt")
            if not isinstance(system_prompt, str) or not system_prompt.strip():
                system_prompt = None
            decision_rule = ""

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
                    decision_rule = self._decision_rule_name(decision)
                    if trace_id is not None:
                        self.openml_store.append_trace_event(
                            trace_id,
                            "decision.route",
                            {
                                "action_type": getattr(decision, "action_type", None),
                                "rule": decision_rule,
                                "confidence": float(getattr(decision, "confidence", 0.0) or 0.0),
                            },
                        )

                if decision is not None and decision.action_type == "tool" and decision.tool in self.tools.list():
                    await self._set_runtime_state(RuntimeState.TOOL_WAIT, "tool_execution_started")
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
                    await self._set_runtime_state(RuntimeState.STREAMING, "tool_execution_finished")

                if decision is not None and decision.action_type == "ask_user" and decision.question and self._should_short_circuit_ask_user(decision):
                    final_text = decision.question
                elif decision is not None and decision.action_type == "final_answer" and decision.final_answer:
                    final_text = decision.final_answer
                else:
                    context = self.memory.load_session(session_id, limit=200)
                    acc: list[str] = []
                    use_sakura = self._is_sakura_enabled() and self.sakura_engine.is_loaded

                    if use_sakura:
                        prompt_messages: list[ChatMsg] = []
                        for item in context:
                            if not isinstance(item, dict):
                                continue
                            role = str(item.get("role", "user"))
                            if role not in {"system", "user", "assistant", "tool"}:
                                continue
                            text = self._message_text(item)
                            if text:
                                prompt_messages.append(ChatMsg(role=role, content=text))

                        if prompt_messages and prompt_messages[-1].role == "user":
                            history = prompt_messages[:-1]
                            prompt_user_message = prompt_messages[-1].content
                        else:
                            history = prompt_messages
                            prompt_user_message = user_text

                        # 2C-7.1: context injection (toggle ON/OFF)
                        context_pack_text: str | None = None
                        context_evidence: list[dict] = []
                        if self.sakura_config.context_enabled and self.sakura_engine.context_ready:
                            ctx_text, evidence, raw_hits = self.sakura_engine.retrieve_context(
                                prompt_user_message,
                            )
                            if ctx_text:
                                context_pack_text = ctx_text
                                context_evidence = [
                                    {"chunk_id": e.chunk_id, "score": e.score, "path": e.path}
                                    for e in evidence
                                ]
                            # 2C-7.3: trace retrieval query
                            if trace_id is not None:
                                self.openml_store.append_trace_event(
                                    trace_id,
                                    "retrieval.query",
                                    {
                                        "query": prompt_user_message[:500],
                                        "top_k": self.sakura_config.retrieval_top_k,
                                        "hits": len(raw_hits),
                                        "top_refs": [
                                            {"chunk_id": h.chunk_id, "score": h.score, "path": h.path}
                                            for h in raw_hits[:5]
                                        ],
                                    },
                                )
                                if context_evidence:
                                    self.openml_store.append_trace_event(
                                        trace_id,
                                        "context.selected",
                                        {
                                            "chunks": context_evidence,
                                            "total_chars": len(context_pack_text or ""),
                                        },
                                    )
                                    self.openml_store.append_trace_event(
                                        trace_id,
                                        "context.pack_built",
                                        {
                                            "char_count": len(context_pack_text or ""),
                                            "chunk_count": len(context_evidence),
                                        },
                                    )

                        prompt = ChatPrompt(
                            system=system_prompt,
                            messages=history,
                            user_message=prompt_user_message,
                            context_pack_text=context_pack_text,
                        )
                        params = self._resolve_gen_params(prompt_user_message)
                        stream_stop_reason = "completed"
                        stream_usage: dict[str, Any] = {}

                        async for event in self.sakura_engine.stream_chat(prompt, params):
                            if event.type == "delta" and event.text:
                                acc.append(event.text)
                                await self._broadcast_notification("chat.delta", {
                                    "session_id": session_id,
                                    "message_id": assistant_id,
                                    "delta": event.text,
                                })
                                await asyncio.sleep(0)
                            elif event.type == "end":
                                if event.stop_reason:
                                    stream_stop_reason = event.stop_reason
                                if isinstance(event.usage, dict):
                                    stream_usage = event.usage

                        await self._broadcast_notification("chat.end", {
                            "session_id": session_id,
                            "message_id": assistant_id,
                            "stop_reason": stream_stop_reason,
                            "usage": stream_usage,
                        })

                        final_text_raw = "".join(acc)
                        final_text, _ = apply_turn_stop(final_text_raw)
                        if trace_id is not None:
                            self.openml_store.append_trace_event(
                                trace_id,
                                "generation.usage",
                                {
                                    "stop_reason": stream_stop_reason,
                                    "usage": stream_usage,
                                    "route": "sakura",
                                    "decision_rule": decision_rule,
                                    "params": {
                                        "max_new_tokens": params.max_new_tokens,
                                        "temperature": params.temperature,
                                        "top_k": params.top_k,
                                        "top_p": params.top_p,
                                        "repetition_penalty": params.repetition_penalty,
                                        "no_repeat_ngram_size": params.no_repeat_ngram_size,
                                    },
                                },
                            )
                    else:
                        async for chunk in self._stream_degraded_reply(user_text):
                            acc.append(chunk)
                            await self._broadcast_notification("chat.delta", {
                                "session_id": session_id,
                                "message_id": assistant_id,
                                "delta": chunk,
                            })
                            await asyncio.sleep(0)

                        await self._broadcast_notification("chat.end", {
                            "session_id": session_id,
                            "message_id": assistant_id,
                            "stop_reason": "degraded_fallback",
                            "usage": {
                                "generated_chars": len("".join(acc)),
                                "generated_tokens": len(acc),
                            },
                        })

                        final_text_raw = "".join(acc)
                        final_text, _ = apply_turn_stop(final_text_raw)
            except Exception as exc:
                await self._set_runtime_state(RuntimeState.ERROR, f"chat_send_failed:{type(exc).__name__}")
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
                    "brain": "SakuraEngine" if (self._is_sakura_enabled() and self.sakura_engine.is_loaded) else "DegradedFallback",
                    "openml": {
                        "action_type": getattr(decision, "action_type", None),
                        "tool": getattr(decision, "tool", None),
                        "rule": decision_rule,
                    },
                    "quality": self._text_quality_metrics(final_text),
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
                        "decision_rule": decision_rule,
                        **self._text_quality_metrics(final_text),
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

            if self.openml_workspace_id is None:
                await self._set_runtime_state(RuntimeState.DEGRADED, "chat_send_completed_workspace_unavailable")
            else:
                await self._set_runtime_state(RuntimeState.READY, "chat_send_completed")

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
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "runtime.state",
                        "params": self._runtime_state_snapshot(),
                    },
                    ensure_ascii=False,
                )
            )
        except Exception:
            pass
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
        logger.info("Genesis Runtime starting on %s:%d", self.host, self.port)
        async with websockets.serve(self._ws_handler, self.host, self.port):
            await asyncio.Future()  # run forever

    def serve(self) -> None:
        """Blocking convenience wrapper."""
        asyncio.run(self.serve_async())

def main() -> None:
    """Standalone entry point for the runtime."""
    logging.basicConfig(level=logging.INFO, format="[Genesis] %(message)s")
    rt = GenesisRuntime()
    rt.serve()


if __name__ == "__main__":
    main()
