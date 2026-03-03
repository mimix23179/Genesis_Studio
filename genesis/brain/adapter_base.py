"""Abstract brain interface for Genesis inference backends.

All brain adapters must implement AbstractBrain so the runtime can swap
backends without changing the rest of the codebase.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BrainMessage:
    """A single message in a conversation (mirroring ChatMsg)."""

    role: str  # "user" | "assistant" | "system" | "tool"
    content: str


@dataclass
class BrainStreamEvent:
    """A single streaming event from a brain backend (mirroring StreamEvent)."""

    type: str  # "begin" | "delta" | "end" | "toolcall"
    text: str | None = None
    stop_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    toolcall: dict[str, Any] | None = None


class AbstractBrain(ABC):
    """Interface every brain backend must satisfy.

    The runtime speaks exclusively to this interface so concrete backends
    (SakuraBrain, future GPU-backed brains, etc.) can be swapped out
    without touching the server code.
    """

    # ── Identity ────────────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Short human-readable name for the backend. e.g. 'SakuraBrain'."""

    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        """True when the underlying model is ready to generate."""

    @property
    def is_available(self) -> bool:
        """Convenience: is_loaded. Subclasses may override for more nuance."""
        return self.is_loaded

    # ── Lifecycle ────────────────────────────────────────────────────

    @abstractmethod
    def load(self, **kwargs: Any) -> None:
        """Load model weights (and tokenizer/config) from whatever source the
        concrete backend uses.  Typically called once at startup.
        """

    @abstractmethod
    def unload(self) -> None:
        """Release model weights and free memory."""

    # ── Generation ──────────────────────────────────────────────────

    @abstractmethod
    def stream_reply(
        self,
        messages: list[BrainMessage],
        *,
        system: str | None = None,
        context: str | None = None,
        max_new_tokens: int = 512,
        temperature: float = 0.75,
        top_k: int = 50,
        top_p: float = 0.9,
        repetition_penalty: float = 1.2,
        seed: int = 42,
    ) -> AsyncIterator[BrainStreamEvent]:
        """Async-generator that yields BrainStreamEvent objects.

        Every implementation MUST yield at least:
        - ``type="begin"``
        - zero or more ``type="delta"`` with ``text!=None``
        - exactly one ``type="end"`` with ``stop_reason`` set
        """
