"""Local llama.cpp brain adapter for Genesis.

Uses llama-cpp-python to load a GGUF model and stream tokens.
No providers, no API keys — just local inference.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from .adapter_base import Brain

logger = logging.getLogger("genesis.brain.llama")


class LocalLlamaBrain(Brain):
    """Brain adapter that uses llama-cpp-python for local inference."""

    def __init__(
        self,
        model_path: str | Path,
        n_ctx: int = 4096,
        n_gpu_layers: int = -1,
        verbose: bool = False,
    ) -> None:
        self.model_path = str(model_path)
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.verbose = verbose
        self._llm: Optional[Any] = None

    def _load(self) -> None:
        """Lazily load the model on first use."""
        if self._llm is not None:
            return

        try:
            from llama_cpp import Llama

            logger.info("Loading model: %s", self.model_path)
            self._llm = Llama(
                model_path=self.model_path,
                n_ctx=self.n_ctx,
                n_gpu_layers=self.n_gpu_layers,
                verbose=self.verbose,
            )
            logger.info("Model loaded successfully")
        except Exception as exc:
            logger.error("Failed to load model: %s", exc)
            raise

    def _build_prompt(self, messages: List[Dict[str, Any]]) -> str:
        """Convert chat messages to a simple prompt string.

        Uses ChatML format which most GGUF models understand.
        """
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            # Extract text from content
            content = msg.get("content", [])
            if isinstance(content, list):
                text = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
            elif isinstance(content, str):
                text = content
            else:
                text = str(content)

            parts.append(f"<|im_start|>{role}\n{text}<|im_end|>")

        parts.append("<|im_start|>assistant\n")
        return "\n".join(parts)

    async def stream_reply(
        self, messages: List[Dict[str, Any]]
    ) -> AsyncIterator[str]:
        """Stream tokens from the local model."""
        self._load()
        if self._llm is None:
            yield "Error: model not loaded."
            return

        prompt = self._build_prompt(messages)

        # Run inference in a thread to avoid blocking the event loop
        loop = asyncio.get_event_loop()

        def _generate():
            return self._llm(
                prompt,
                max_tokens=2048,
                temperature=0.7,
                top_p=0.9,
                stream=True,
                stop=["<|im_end|>", "<|im_start|>"],
            )

        stream = await loop.run_in_executor(None, _generate)

        for chunk in stream:
            choices = chunk.get("choices", [])
            if choices:
                text = choices[0].get("text", "")
                if text:
                    # Yield each character for ultra-smooth streaming
                    for ch in text:
                        yield ch
                        await asyncio.sleep(0)

    async def is_available(self) -> bool:
        try:
            self._load()
            return self._llm is not None
        except Exception:
            return False
