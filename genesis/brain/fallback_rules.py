"""Fallback rules brain — keeps Genesis alive when no model is loaded.

This brain doesn't need any model file. It responds with helpful
deterministic messages and can still execute tools.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, List

from .adapter_base import Brain


class FallbackRulesBrain(Brain):
    """No-model fallback. Genesis still works — just without inference."""

    GREETING = (
        "I'm Genesis, running in fallback mode. "
        "No model is loaded right now, but I can still:\n\n"
        "• Read and write files\n"
        "• Search your workspace\n"
        "• Run tools and commands\n"
        "• Manage your conversations\n\n"
        "Load a GGUF model into `./models/` and I'll come fully alive."
    )

    async def stream_reply(
        self, messages: List[Dict[str, Any]]
    ) -> AsyncIterator[str]:
        """Stream the fallback message character by character."""
        text = self.GREETING
        for ch in text:
            yield ch
            # Tiny delay for smooth per-char streaming effect
            await asyncio.sleep(0.008)

    async def is_available(self) -> bool:
        return True
