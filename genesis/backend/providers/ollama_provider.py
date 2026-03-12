from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
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

    def collect_stream(self, history: list[dict[str, Any]]) -> Iterator[str]:
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
                        yield piece
        except requests.HTTPError as exc:
            logger.warning("Ollama stream failed: %s", exc)
            yield self._build_chat_failure_message(exc, payload=payload)
        except Exception as exc:
            logger.warning("Ollama stream failed: %s", exc)
            yield self._build_chat_failure_message(exc)

    def _extract_response_error(self, response: requests.Response | None) -> str:
        if response is None:
            return ""
        try:
            payload = response.json() if response.content else {}
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            error = payload.get("error")
            if error is not None:
                return str(error).strip()
        try:
            return response.text.strip()
        except Exception:
            return ""

    def _probe_chat_error(self, payload: dict[str, Any]) -> str:
        try:
            probe_payload = dict(payload)
            probe_payload["stream"] = False
            response = requests.post(
                f"{self.ollama_base_url}/api/chat",
                json=probe_payload,
                timeout=min(self.request_timeout, 20.0),
            )
            if response.ok:
                return ""
            return self._extract_response_error(response)
        except Exception:
            return ""

    def _build_chat_failure_message(self, exc: Exception, payload: dict[str, Any] | None = None) -> str:
        if isinstance(exc, requests.HTTPError):
            response = exc.response
            status_code = response.status_code if response is not None else None
            response_error = self._extract_response_error(response)
            if not response_error and payload:
                response_error = self._probe_chat_error(payload)
            if status_code == 404 and "model" in response_error.lower() and "not found" in response_error.lower():
                models_payload = self.list_models_payload()
                available = []
                if bool(models_payload.get("ok", False)):
                    available = [
                        str(item.get("name", "")).strip()
                        for item in models_payload.get("models", [])
                        if isinstance(item, dict) and str(item.get("name", "")).strip()
                    ]
                if self.model in available:
                    return (
                        f"Ollama rejected model '{self.model}' even though it appears in the installed list. "
                        "The local model store is inconsistent; re-pull the model from Genesis Models."
                    )
                if available:
                    joined = ", ".join(available[:4])
                    return (
                        f"Selected model '{self.model}' is not usable on the current Ollama runtime. "
                        f"Available models: {joined}."
                    )
                return (
                    f"Selected model '{self.model}' is not available on the current Ollama runtime. "
                    "Pull it from Genesis Models or choose another installed model."
                )
            if response_error:
                return f"Ollama request failed: {response_error}"

        return (
            "Ollama backend is unavailable. Ensure `ollama serve` is running and the configured runtime is reachable "
            f"(current model: {self.model}, base URL: {self.ollama_base_url})."
        )

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
            "ollama_models_dir": os.environ.get("GENESIS_OLLAMA_MODELS_DIR", os.environ.get("OLLAMA_MODELS", "")),
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

    def list_models_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": True,
            "model": self.model,
            "ollama_base_url": self.ollama_base_url,
        }
        try:
            response = requests.get(
                f"{self.ollama_base_url}/api/tags",
                timeout=min(self.request_timeout, 8.0),
            )
            response.raise_for_status()
            body = response.json() if response.content else {}
            models_raw = body.get("models") if isinstance(body, dict) else []
            items: list[dict[str, Any]] = []
            if isinstance(models_raw, list):
                for item in models_raw:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name", "")).strip()
                    if not name:
                        continue
                    items.append(
                        {
                            "name": name,
                            "size": item.get("size"),
                            "digest": item.get("digest"),
                            "modified_at": item.get("modified_at"),
                        }
                    )
            payload["models"] = items
            payload["count"] = len(items)
            payload["model_loaded"] = any(m.get("name") == self.model for m in items)
            return payload
        except Exception as exc:
            payload["ok"] = False
            payload["error"] = str(exc)
            payload["models"] = []
            payload["count"] = 0
            payload["model_loaded"] = False
            return payload

    def set_active_model(self, model: str) -> dict[str, Any]:
        target = str(model or "").strip()
        if not target:
            return {"ok": False, "error": "Model cannot be empty.", "model": self.model}
        self.model = target
        return {"ok": True, "model": self.model}

    def set_base_url(self, base_url: str) -> dict[str, Any]:
        target = str(base_url or "").strip().rstrip("/")
        if not target:
            return {"ok": False, "error": "Ollama base URL cannot be empty.", "ollama_base_url": self.ollama_base_url}
        self.ollama_base_url = target
        return {"ok": True, "ollama_base_url": self.ollama_base_url}

    def _request_keep_alive(self, *, model: str, keep_alive: str | int, unload: bool = False) -> dict[str, Any]:
        timeout = max(15.0, min(self.request_timeout, 90.0))
        candidates = [
            (
                "/api/chat",
                {
                    "model": model,
                    "messages": [{"role": "user", "content": " "}],
                    "stream": False,
                    "keep_alive": keep_alive,
                },
            ),
            (
                "/api/generate",
                {
                    "model": model,
                    "prompt": " ",
                    "stream": False,
                    "keep_alive": keep_alive,
                },
            ),
        ]
        tried: list[str] = []

        for endpoint, payload in candidates:
            try:
                response = requests.post(
                    f"{self.ollama_base_url}{endpoint}",
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                body = response.json() if response.content else {}
                return {
                    "ok": True,
                    "model": model,
                    "loaded": not unload,
                    "response": body,
                    "endpoint": endpoint,
                }
            except requests.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                response_error = self._extract_response_error(exc.response)
                if status_code == 404:
                    if "model" in response_error.lower() and "not found" in response_error.lower():
                        return {
                            "ok": False,
                            "model": model,
                            "loaded": not unload,
                            "error": (
                                f"Ollama reported model '{model}' as unavailable. "
                                "Re-pull it from Genesis Models before loading."
                            ),
                            "endpoint": endpoint,
                        }
                    tried.append(endpoint)
                    continue
                return {
                    "ok": False,
                    "model": model,
                    "loaded": not unload,
                    "error": response_error or str(exc),
                    "endpoint": endpoint,
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "model": model,
                    "loaded": not unload,
                    "error": str(exc),
                    "endpoint": endpoint,
                }

        if unload:
            return {
                "ok": True,
                "model": model,
                "loaded": False,
                "warning": "Unload endpoint unavailable; runtime selection cleared without remote unload.",
                "endpoint": None,
            }

        models_payload = self.list_models_payload()
        if bool(models_payload.get("ok", False)):
            installed_models = {
                str(item.get("name", "")).strip()
                for item in models_payload.get("models", [])
                if isinstance(item, dict) and str(item.get("name", "")).strip()
            }
            if model in installed_models:
                self.model = model
                return {
                    "ok": True,
                    "model": model,
                    "loaded": True,
                    "endpoint": None,
                    "warning": "Preload endpoint unavailable; model will load on the first Genesis request.",
                }

        return {
            "ok": False,
            "model": model,
            "loaded": False,
            "error": "No compatible Ollama keep-alive endpoint available.",
            "detail": ", ".join(tried),
        }

    def load_model_payload(self, *, model: str | None = None, keep_alive: str = "30m") -> dict[str, Any]:
        target = str(model or self.model).strip()
        if not target:
            return {"ok": False, "error": "Model cannot be empty.", "model": self.model}
        result = self._request_keep_alive(model=target, keep_alive=keep_alive, unload=False)
        if bool(result.get("ok", False)):
            self.model = target
        return result

    def unload_model_payload(self, *, model: str | None = None) -> dict[str, Any]:
        target = str(model or self.model).strip()
        if not target:
            return {"ok": False, "error": "Model cannot be empty.", "model": self.model}
        return self._request_keep_alive(model=target, keep_alive=0, unload=True)

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

    def suggest_session_title(self, text: str) -> str:
        prompt_text = " ".join(str(text or "").split()).strip()
        if not prompt_text:
            return "New Conversation"

        trimmed = prompt_text[:800]
        payload = {
            "model": self.model,
            "prompt": (
                "Write a short conversation title of 2 to 6 words based on this user request. "
                "Return only the title text with no quotes or punctuation wrapper.\n\n"
                f"Request: {trimmed}"
            ),
            "stream": False,
            "options": {"temperature": 0.2},
        }

        try:
            response = requests.post(
                f"{self.ollama_base_url}/api/generate",
                json=payload,
                timeout=min(self.request_timeout, 20.0),
            )
            response.raise_for_status()
            body = response.json() if response.content else {}
            candidate = str(body.get("response", "")).strip()
            normalized = self._normalize_title(candidate)
            if normalized:
                return normalized
        except Exception:
            pass

        return self._normalize_title(trimmed) or "New Conversation"

    @staticmethod
    def _normalize_title(text: str) -> str:
        candidate = str(text or "").strip().strip("\"'")
        if not candidate:
            return ""
        lowered = candidate.lower()
        for prefix in ("title:", "conversation title:", "topic:"):
            if lowered.startswith(prefix):
                candidate = candidate[len(prefix):].strip()
                break
        words = candidate.replace("\n", " ").split()
        if not words:
            return ""
        shortened = " ".join(words[:6]).strip(" -:;,.")
        return shortened[:64]
