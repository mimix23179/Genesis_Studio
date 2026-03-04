from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from ..providers import OllamaProvider
from .session_service import SessionService

RUNTIME_NAME = "genesis-ollama-runtime"
RUNTIME_API_VERSION = "0.1.0"
RUNTIME_PROTOCOL = "jsonrpc-2.0"

SUPPORTED_RPC_METHODS = [
    "workspace.set",
    "session.list",
    "session.create",
    "session.open",
    "chat.send",
    "tool.list",
    "tool.call",
    "tool.execute",
    "tool.result",
    "ui.event",
    "openml.status",
    "openml.dataset.export",
    "runtime.info",
    "runtime.health",
    "runtime.api_version",
]

SUPPORTED_NOTIFY_EVENTS = [
    "session.updated",
    "chat.begin",
    "chat.delta",
    "chat.message",
]


class RuntimeService:
    """Runtime metadata, workspace, and health service."""

    def __init__(
        self,
        *,
        provider: OllamaProvider,
        session_service: SessionService,
        workspace_getter: Callable[[], str],
        workspace_setter: Callable[[str], None],
        started_at: float | None = None,
        now_factory: Callable[[], float] | None = None,
    ) -> None:
        self._provider = provider
        self._sessions = session_service
        self._workspace_getter = workspace_getter
        self._workspace_setter = workspace_setter
        self._now = now_factory or time.time
        self._started_at = float(started_at if started_at is not None else self._now())

    def api_version(self) -> dict[str, Any]:
        return {"api_version": RUNTIME_API_VERSION}

    def info(self) -> dict[str, Any]:
        uptime = max(0.0, self._now() - self._started_at)
        return {
            "ok": True,
            "name": RUNTIME_NAME,
            "backend": "ollama",
            "protocol": RUNTIME_PROTOCOL,
            "api_version": RUNTIME_API_VERSION,
            "model": self._provider.model,
            "ollama_base_url": self._provider.ollama_base_url,
            "workspace_root": self._workspace_getter(),
            "uptime_sec": round(uptime, 3),
            "session_count": self._sessions.session_count(),
            "supported_methods": list(SUPPORTED_RPC_METHODS),
            "notify_events": list(SUPPORTED_NOTIFY_EVENTS),
        }

    async def health(self) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._provider.health_payload,
            api_version=RUNTIME_API_VERSION,
            workspace_root=self._workspace_getter(),
            session_count=self._sessions.session_count(),
        )

    def set_workspace(self, root: str) -> dict[str, Any]:
        clean_root = str(root).strip()
        if clean_root:
            self._workspace_setter(clean_root)
        return {"ok": True, "root": self._workspace_getter()}
