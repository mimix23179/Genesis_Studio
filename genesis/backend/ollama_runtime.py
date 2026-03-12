from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from .providers import OllamaProvider
from .services import ChatService, RuntimeService, SessionService, ToolService
from .transport import JsonRpcWebSocketServer

logger = logging.getLogger("genesis.ollama")


class OllamaRuntime:
    """
    JSON-RPC runtime facade.

    Internals are split into:
    - transport: websocket/json-rpc server
    - services: runtime/session/chat/tool orchestration
    - provider: Ollama HTTP adapter
    """

    def __init__(
        self,
        *,
        model: str = "qwen2.5-coder:7b",
        ollama_base_url: str = "http://127.0.0.1:11434",
        request_timeout: float = 120.0,
    ) -> None:
        self.workspace_root = str(Path.cwd())
        self._started_at = time.time()

        self._provider = OllamaProvider(
            model=model,
            ollama_base_url=ollama_base_url,
            request_timeout=request_timeout,
        )
        self._sessions = SessionService(storage_path=Path.cwd() / "data" / "conversations.json")
        self._runtime = RuntimeService(
            provider=self._provider,
            session_service=self._sessions,
            workspace_getter=self._get_workspace_root,
            workspace_setter=self._set_workspace_root,
            started_at=self._started_at,
        )
        self._tools = ToolService()
        self._chat = ChatService(
            session_service=self._sessions,
            provider=self._provider,
            notify=self._notify,
        )

        self._transport = JsonRpcWebSocketServer(self._dispatch_method, logger=logger)

    async def start(self, host: str, port: int):
        server = await self._transport.start(host, port)
        logger.info("Ollama runtime listening at ws://%s:%s", host, port)
        return server

    async def _dispatch_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "runtime.api_version":
            return self._runtime.api_version()

        if method == "runtime.info":
            return self._runtime.info()

        if method == "runtime.health":
            return await self._runtime.health()

        if method == "runtime.models.list":
            return self._provider.list_models_payload()

        if method == "runtime.base_url.set":
            return self._provider.set_base_url(str(params.get("ollama_base_url", "")).strip())

        if method == "runtime.model.set":
            return self._provider.set_active_model(str(params.get("model", "")).strip())

        if method == "runtime.model.load":
            return self._provider.load_model_payload(
                model=str(params.get("model", "")).strip() or None,
                keep_alive=str(params.get("keep_alive", "30m")).strip() or "30m",
            )

        if method == "runtime.model.unload":
            return self._provider.unload_model_payload(
                model=str(params.get("model", "")).strip() or None
            )

        if method == "workspace.set":
            return self._runtime.set_workspace(str(params.get("root", "")))

        if method == "session.list":
            return {"sessions": self._sessions.list_sessions()}

        if method == "session.create":
            title = str(params.get("title", "New Conversation"))
            active_model = str(params.get("active_model", "")).strip() or self._provider.model
            created = self._sessions.create_session(title, active_model=active_model)
            await self._notify(
                "session.updated",
                {
                    "session_id": created["session_id"],
                    "action": "created",
                    "title": created["title"],
                },
            )
            return created

        if method == "session.open":
            session_id = str(params.get("session_id", "")).strip()
            return self._sessions.open_session(session_id)

        if method == "chat.send":
            return await self._chat.send(params)

        if method in ToolService.PLACEHOLDER_METHODS:
            return self._tools.handle(method, params)

        raise ValueError(f"Unknown method: {method}")

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._transport.notify(method, params)

    def _get_workspace_root(self) -> str:
        return self.workspace_root

    def _set_workspace_root(self, value: str) -> None:
        self.workspace_root = str(value).strip() or self.workspace_root
