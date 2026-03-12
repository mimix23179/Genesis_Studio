from __future__ import annotations

import logging
import os
import socket
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger("genesis.ollama.bootstrap")


@dataclass(frozen=True)
class OllamaBootstrapResult:
    ok: bool
    base_url: str
    models_dir: str
    model: str
    reachable: bool
    server_started: bool
    model_present: bool
    model_pulled: bool
    message: str
    error: str | None = None


class OllamaWorkspaceBootstrap:
    """Ensures Ollama uses a workspace-local models directory and model availability."""

    _DEFAULT_MODELS_DIR = "models/ollama"

    def __init__(
        self,
        *,
        workspace_root: Path,
        ollama_base_url: str,
        model: str,
        models_dir: str | Path | None = None,
        auto_pull: bool = True,
        request_timeout: float = 120.0,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.ollama_base_url = str(ollama_base_url or "http://127.0.0.1:11434").rstrip("/")
        self.model = str(model or "").strip()
        self.auto_pull = bool(auto_pull)
        self.request_timeout = max(5.0, float(request_timeout))
        self.models_dir = self._resolve_models_dir(models_dir)
        self._serve_process: subprocess.Popen[bytes] | None = None

    def update_config(
        self,
        *,
        ollama_base_url: str | None = None,
        model: str | None = None,
        models_dir: str | Path | None = None,
        auto_pull: bool | None = None,
        request_timeout: float | None = None,
    ) -> None:
        if ollama_base_url is not None:
            self.ollama_base_url = str(ollama_base_url).strip().rstrip("/") or self.ollama_base_url
        if model is not None:
            self.model = str(model).strip()
        if models_dir is not None:
            self.models_dir = self._resolve_models_dir(models_dir)
        if auto_pull is not None:
            self.auto_pull = bool(auto_pull)
        if request_timeout is not None:
            self.request_timeout = max(5.0, float(request_timeout))

    def prepare(self) -> OllamaBootstrapResult:
        models_dir = self.models_dir
        models_dir.mkdir(parents=True, exist_ok=True)

        # Keep the process environment aligned for terminal and child processes.
        os.environ["GENESIS_OLLAMA_MODELS_DIR"] = str(models_dir)
        os.environ["OLLAMA_MODELS"] = str(models_dir)

        scheme, host, port = self._parse_base_url(self.ollama_base_url)
        host_port = f"{host}:{port}"
        server_started = self._start_server(host_port)
        if not server_started:
            # Port is likely occupied by a global/system daemon. Start a Genesis-owned server
            # on the next available local port so model pulls use workspace/models/ollama.
            fallback_port = self._find_available_port(host=host, start=max(1025, port + 1))
            if fallback_port is not None:
                host_port = f"{host}:{fallback_port}"
                self.ollama_base_url = self._build_base_url(scheme=scheme, host=host, port=fallback_port)
                server_started = self._start_server(host_port)

        os.environ["GENESIS_OLLAMA_BASE_URL"] = self.ollama_base_url
        os.environ["OLLAMA_HOST"] = host_port

        if server_started:
            reachable = self._wait_reachable(timeout_s=12.0)
        else:
            reachable = False

        if not reachable:
            return OllamaBootstrapResult(
                ok=False,
                base_url=self.ollama_base_url,
                models_dir=str(models_dir),
                model=self.model,
                reachable=False,
                server_started=server_started,
                model_present=False,
                model_pulled=False,
                message="Unable to reach Ollama API",
                error="Unable to start or reach Genesis-managed Ollama server.",
            )

        available_models = self._list_models()
        model_present = self.model in available_models if self.model else True
        model_pulled = False
        pull_error: str | None = None

        if self.auto_pull and self.model and not model_present:
            model_pulled, pull_error = self._pull_model(self.model, host_port)
            if model_pulled:
                available_models = self._list_models()
                model_present = self.model in available_models

        ok = reachable and (model_present or not self.auto_pull or not self.model)
        if ok:
            message = (
                "Ollama ready with workspace model store"
                if model_present
                else "Ollama reachable (model pull disabled)"
            )
        else:
            message = "Ollama reachable but target model is unavailable"

        return OllamaBootstrapResult(
            ok=ok,
            base_url=self.ollama_base_url,
            models_dir=str(models_dir),
            model=self.model,
            reachable=reachable,
            server_started=server_started,
            model_present=model_present,
            model_pulled=model_pulled,
            message=message,
            error=pull_error,
        )

    def _start_server(self, host_port: str | None) -> bool:
        existing = self._serve_process
        if existing is not None and existing.poll() is None:
            return True
        executable = shutil.which("ollama")
        if not executable:
            return False

        env = self._process_env(host_port)
        creationflags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags |= int(subprocess.CREATE_NO_WINDOW)

        try:
            process = subprocess.Popen(
                [executable, "serve"],
                cwd=str(self.workspace_root),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            # If the process dies immediately (for example, port in use), treat as failure.
            time.sleep(0.25)
            if process.poll() is not None:
                logger.warning(
                    "Local Ollama server exited immediately (host=%s, exit=%s)",
                    host_port or "default",
                    process.returncode,
                )
                self._serve_process = None
                return False
            self._serve_process = process
            logger.info(
                "Started local Ollama server for Genesis (host=%s, models=%s)",
                host_port or "default",
                self.models_dir,
            )
            return True
        except Exception:
            logger.exception("Failed to start local Ollama server")
            self._serve_process = None
            return False

    def _pull_model(self, model: str, host_port: str | None) -> tuple[bool, str | None]:
        executable = shutil.which("ollama")
        if not executable:
            return False, "`ollama` executable not found in PATH."

        env = self._process_env(host_port)
        timeout_s = max(300.0, self.request_timeout * 8.0)
        try:
            completed = subprocess.run(
                [executable, "pull", model],
                cwd=str(self.workspace_root),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, f"`ollama pull {model}` timed out after {int(timeout_s)} seconds."
        except Exception as exc:
            return False, str(exc)

        if completed.returncode == 0:
            logger.info("Pulled Ollama model '%s' into %s", model, self.models_dir)
            return True, None

        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout or f"exit code {completed.returncode}"
        return False, detail

    def _list_models(self) -> list[str]:
        try:
            response = requests.get(
                f"{self.ollama_base_url}/api/tags",
                timeout=min(self.request_timeout, 8.0),
            )
            response.raise_for_status()
            payload = response.json() if response.content else {}
        except Exception:
            return []

        models_raw = payload.get("models") if isinstance(payload, dict) else []
        if not isinstance(models_raw, list):
            return []
        names: list[str] = []
        for item in models_raw:
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name.strip():
                    names.append(name.strip())
        return names

    def _is_reachable(self) -> bool:
        try:
            response = requests.get(
                f"{self.ollama_base_url}/api/tags",
                timeout=min(self.request_timeout, 3.0),
            )
            return response.status_code < 500
        except Exception:
            return False

    def _wait_reachable(self, *, timeout_s: float) -> bool:
        deadline = time.monotonic() + max(0.1, float(timeout_s))
        while time.monotonic() < deadline:
            if self._is_reachable():
                return True
            time.sleep(0.25)
        return False

    def _process_env(self, host_port: str | None) -> dict[str, str]:
        env = dict(os.environ)
        env["OLLAMA_MODELS"] = str(self.models_dir)
        env["GENESIS_OLLAMA_MODELS_DIR"] = str(self.models_dir)
        if host_port:
            env["OLLAMA_HOST"] = host_port
        return env

    def _resolve_models_dir(self, value: str | Path | None) -> Path:
        if value is None:
            return (self.workspace_root / self._DEFAULT_MODELS_DIR).resolve()
        candidate = Path(str(value).strip() or self._DEFAULT_MODELS_DIR)
        if candidate.is_absolute():
            return candidate.resolve()
        return (self.workspace_root / candidate).resolve()

    @staticmethod
    def _host_port(base_url: str) -> str | None:
        try:
            parsed = urlparse(base_url)
        except Exception:
            return None
        hostname = (parsed.hostname or "").strip()
        if not hostname:
            return None
        port = parsed.port
        if port is None:
            port = 443 if (parsed.scheme or "").lower() == "https" else 80
        return f"{hostname}:{int(port)}"

    @staticmethod
    def _parse_base_url(base_url: str) -> tuple[str, str, int]:
        try:
            parsed = urlparse(base_url)
        except Exception:
            return "http", "127.0.0.1", 11434
        scheme = (parsed.scheme or "http").strip().lower() or "http"
        host = (parsed.hostname or "127.0.0.1").strip() or "127.0.0.1"
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        port = parsed.port
        if port is None:
            port = 443 if scheme == "https" else 11434
        return scheme, host, int(port)

    @staticmethod
    def _build_base_url(*, scheme: str, host: str, port: int) -> str:
        clean_scheme = (scheme or "http").strip().lower() or "http"
        clean_host = (host or "127.0.0.1").strip() or "127.0.0.1"
        return f"{clean_scheme}://{clean_host}:{int(port)}"

    @staticmethod
    def _find_available_port(*, host: str, start: int, max_scan: int = 24) -> int | None:
        for offset in range(max(1, int(max_scan))):
            candidate = int(start) + offset
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sock.bind((host, candidate))
                except OSError:
                    continue
                return candidate
        return None
