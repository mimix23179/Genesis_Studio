"""SakuraBrain — the real local inference brain backed by a jadepack.

SakuraBrain wraps SakuraEngine and exposes both:
- The low-level engine API (forwarded methods) so the runtime can call
  context/retrieval operations exactly as before.
- The high-level AbstractBrain interface (stream_reply) for clean
  callers that don't care about internals.

Usage
-----
    brain = SakuraBrain(jadepack_path="data/openml/jade/sakura_v1.jadepack")
    brain.load_from_jadepack(brain.jadepack_path)

    # High-level:
    async for event in brain.stream_reply(messages, system="You are Genesis..."):
        print(event.text, end="", flush=True)

    # Low-level (runtime-style):
    async for event in brain.stream_chat(prompt, params):
        ...
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from .adapter_base import AbstractBrain, BrainMessage, BrainStreamEvent
from ..openml.sakura import (
    ChatMsg,
    ChatPrompt,
    GenParams,
    SakuraEngine,
    SakuraRuntimeConfig,
    StreamEvent,
)
from ..openml.sakura.context.bm25_index import BM25Index
from ..openml.sakura.context.chunker import Chunk

logger = logging.getLogger("genesis.brain")

# Default system prompt injected when none is provided.
DEFAULT_SYSTEM_PROMPT = (
    "You are Genesis, a helpful offline AI assistant. "
    "Answer the user's question directly and concisely. "
    "Do not repeat yourself. "
    "Stay on topic. "
    "If you are unsure, ask a short clarifying question."
)


class SakuraBrain(AbstractBrain):
    """Real local inference brain using Sakura weights loaded from a jadepack.

    This class is the **single source of truth** for AI generation in Genesis.
    It owns the SakuraEngine instance and exposes all the interfaces the
    runtime needs:

    - ``load_from_jadepack(path)``  — loads weights + tokenizer + config
    - ``stream_chat(prompt, params)`` — low-level streaming (StreamEvent)
    - ``stream_reply(messages, ...)`` — high-level streaming (BrainStreamEvent)
    - ``build_context_index(docs)``   — BM25 context index
    - ``retrieve_context(query)``     — retrieval lookup
    """

    def __init__(
        self,
        jadepack_path: str = "",
        config: SakuraRuntimeConfig | None = None,
    ) -> None:
        self._jadepack_path = jadepack_path
        self._config = config or SakuraRuntimeConfig(
            jadepack_path=jadepack_path,
            enabled=bool(jadepack_path),
        )
        self._engine = SakuraEngine(self._config)

    # ── Identity ────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "SakuraBrain"

    @property
    def is_loaded(self) -> bool:
        return self._engine.is_loaded

    @property
    def context_ready(self) -> bool:
        return self._engine.context_ready

    @property
    def jadepack_path(self) -> str:
        return self._jadepack_path

    @property
    def config(self) -> SakuraRuntimeConfig:
        return self._config

    # ── Engine passthrough (keeps ws_server.py minimal) ─────────────

    @property
    def _chunks(self) -> dict[str, Chunk]:
        """Direct access to engine chunks (for Abyss storage)."""
        return self._engine._chunks

    # ── AbstractBrain lifecycle ──────────────────────────────────────

    def load(self, jadepack_path: str = "", **kwargs: Any) -> None:
        """Load weights from jadepack.  Alias for load_from_jadepack."""
        path = jadepack_path or self._jadepack_path
        if path:
            self.load_from_jadepack(path)

    def unload(self) -> None:
        self._engine.unload()

    # ── Jadepack loading (primary API) ───────────────────────────────

    def load_from_jadepack(self, jadepack_path: str) -> None:
        """Verify and load a jadepack into the Sakura engine.

        Raises
        ------
        ValueError
            If the jadepack fails integrity verification or weight shapes
            do not match the config.
        """
        self._engine.load_from_jadepack(jadepack_path)
        self._jadepack_path = jadepack_path
        self._config.jadepack_path = jadepack_path
        logger.info("SakuraBrain loaded from jadepack: %s", jadepack_path)

    # ── Context index (forwarded to engine) ──────────────────────────

    def build_context_index(self, documents: list[dict[str, str]]) -> dict[str, Any]:
        """Chunk documents and build a BM25 retrieval index.

        Parameters
        ----------
        documents:
            List of ``{"path": str, "text": str}`` dicts.
        """
        return self._engine.build_context_index(documents)

    def load_context_index(self, chunks: list[Chunk], index: BM25Index) -> None:
        """Restore a pre-built index directly."""
        self._engine.load_context_index(chunks, index)

    def retrieve_context(
        self,
        query: str,
        *,
        top_k: int | None = None,
    ) -> tuple[str, list[Any], list[Any]]:
        """Retrieve relevant context chunks for the given query.

        Returns
        -------
        (context_pack_text, evidence, raw_hits)
        """
        return self._engine.retrieve_context(query, top_k=top_k)

    # ── Low-level streaming (StreamEvent) ────────────────────────────

    async def stream_chat(
        self,
        prompt: ChatPrompt,
        params: GenParams,
    ) -> AsyncIterator[StreamEvent]:
        """Thin delegation to SakuraEngine.stream_chat.

        Use this when you need full control over the ChatPrompt / GenParams
        objects (as the runtime does).
        """
        async for event in self._engine.stream_chat(prompt, params):
            yield event

    # ── High-level streaming (BrainStreamEvent) ──────────────────────

    async def stream_reply(
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
        """High-level streaming API: converts BrainMessage → ChatPrompt internally.

        Yields BrainStreamEvent objects — ideal for callers that don't need
        to know about the Sakura internals.
        """
        chat_messages = [ChatMsg(role=m.role, content=m.content) for m in messages]

        # Separate last user message from history
        user_message = ""
        history: list[ChatMsg] = []
        if chat_messages and chat_messages[-1].role == "user":
            user_message = chat_messages[-1].content
            history = chat_messages[:-1]
        else:
            history = chat_messages

        prompt = ChatPrompt(
            system=system or DEFAULT_SYSTEM_PROMPT,
            messages=history,
            user_message=user_message,
            context_pack_text=context,
        )
        params = GenParams(
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_k=top_k,
            top_p=top_p,
            repetition_penalty=repetition_penalty,
            seed=seed,
        )

        async for event in self._engine.stream_chat(prompt, params):
            yield BrainStreamEvent(
                type=event.type,
                text=event.text,
                stop_reason=event.stop_reason,
                usage=event.usage if isinstance(event.usage, dict) else {},
            )

    # ── Diagnostics ──────────────────────────────────────────────────

    def describe(self) -> dict[str, Any]:
        """Return a snapshot dict for runtime.info / health check."""
        return {
            "name": self.name,
            "is_loaded": self.is_loaded,
            "jadepack_path": self._jadepack_path,
            "context_ready": self.context_ready,
            "context_enabled": self._config.context_enabled,
        }
