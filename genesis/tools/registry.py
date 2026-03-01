"""Tool registry for Genesis.

Tools are deterministic, model-independent operations.
They survive any brain swap. This is the durable backbone.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List


ToolFn = Callable[[dict], Awaitable[dict]]


class ToolRegistry:
    """Registry of available tools that the brain can invoke."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolFn] = {}

    def register(self, name: str, fn: ToolFn) -> None:
        """Register a tool function by name."""
        self._tools[name] = fn

    def get(self, name: str) -> ToolFn:
        """Get a tool function by name. Raises KeyError if not found."""
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools[name]

    def list(self) -> List[str]:
        """List all registered tool names."""
        return sorted(self._tools.keys())

    def describe(self) -> List[Dict[str, Any]]:
        """Return a list of tool descriptions for the brain."""
        return [
            {"name": name, "doc": (fn.__doc__ or "").strip()}
            for name, fn in sorted(self._tools.items())
        ]
