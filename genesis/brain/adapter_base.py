"""Abstract Brain interface for Genesis.

The Brain is the replaceable 'engine' of Genesis.
Everything else (bus, tools, memory, UI) is stable.
The Brain can be swapped at runtime without breaking anything.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List


class Brain(ABC):
    """Abstract base class for all Genesis brain adapters."""

    @abstractmethod
    async def stream_reply(
        self, messages: List[Dict[str, Any]]
    ) -> AsyncIterator[str]:
        """Yield small text chunks (even single characters) for smooth streaming.

        Args:
            messages: The conversation history as a list of message dicts.

        Yields:
            str: Small text chunks to be streamed to the UI.
        """
        raise NotImplementedError
        # Make this a proper async generator
        yield  # pragma: no cover

    async def is_available(self) -> bool:
        """Check whether this brain is ready to generate."""
        return True

    def name(self) -> str:
        return type(self).__name__
