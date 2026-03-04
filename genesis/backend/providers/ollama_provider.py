from __future__ import annotations

import json
import logging
from typing import Any

import requests

logger = logging.getLogger("genesis.ollama.provider")


class OllamaProvider:
    """Thin provider adapter around Ollama HTTP APIs."""

    def __init__(
        self,
        *,
        model: str = "qwen2.5-coder:7b",
        ollama_base_url: str = "http://127.0.0.1:11434",
        request_timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.request_timeout = request_timeout

    def collect_stream(self, history: list[dict[str, Any]]) -> list[str]:
        messages = []
        for item in history:
            role = str(item.get("role", "user"))
            content = self.extract_message_text(item)
            if not content:
                continue
            messages.append({"role": role, "content": content})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }

        chunks: list[str] = []
        url = f"{self.ollama_base_url}/api/chat"

        try:
            with requests.post(url, json=payload, stream=True, timeout=self.request_timeout) as response:
                response.raise_for_status()
                for raw_line in response.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue
                    try:
                        event = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    message = event.get("message") if isinstance(event.get("message"), dict) else {}
                    piece = str(message.get("content", ""))
                    if piece:
                        chunks.append(piece)
        except Exception as exc:
            logger.warning("Ollama stream failed: %s", exc)
            chunks.append(
                "Ollama backend is unavailable. Ensure `ollama serve` is running and a model is pulled "
                f"(current model: {self.model})."
            )

        return chunks

    def health_payload(
        self,
        *,
        api_version: str,
        workspace_root: str,
        session_count: int,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": True,
            "backend": "ollama",
            "api_version": api_version,
            "model": self.model,
            "ollama_base_url": self.ollama_base_url,
            "workspace_root": workspace_root,
            "session_count": int(session_count),
        }
        try:
            response = requests.get(
                f"{self.ollama_base_url}/api/tags",
                timeout=min(self.request_timeout, 5.0),
            )
            response.raise_for_status()
            body = response.json() if response.content else {}
            models_raw = body.get("models") if isinstance(body, dict) else []
            model_names: list[str] = []
            if isinstance(models_raw, list):
                for item in models_raw:
                    if isinstance(item, dict):
                        name = item.get("name")
                        if isinstance(name, str) and name.strip():
                            model_names.append(name.strip())
            payload["ollama_reachable"] = True
            payload["available_models"] = model_names
            payload["model_loaded"] = self.model in model_names
        except Exception as exc:
            payload["ok"] = False
            payload["ollama_reachable"] = False
            payload["error"] = str(exc)
        return payload

    @staticmethod
    def extract_message_text(message: dict[str, Any]) -> str:
        content = message.get("content", [])
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text is not None:
                        parts.append(str(text))
            return "".join(parts).strip()
        if isinstance(content, str):
            return content.strip()
        return ""
