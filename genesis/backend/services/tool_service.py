from __future__ import annotations

from typing import Any


class ToolService:
    """Phase-1 placeholder for tool APIs (wired, not fully implemented yet)."""

    PLACEHOLDER_METHODS = {
        "tool.list",
        "tool.call",
        "tool.execute",
        "tool.result",
        "ui.event",
        "openml.status",
        "openml.dataset.export",
    }

    def handle(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        _ = params
        if method not in self.PLACEHOLDER_METHODS:
            raise ValueError(f"Unknown tool method: {method}")
        return {"ok": True, "backend": "ollama", "method": method}
