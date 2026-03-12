from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Sequence

try:
    import winpty
except Exception:  # pragma: no cover - optional dependency on non-Windows hosts.
    winpty = None


class TerminalSession:
    """Cross-shell terminal session with a PTY backend on Windows."""

    _READ_CHUNK = 4096

    def __init__(
        self,
        *,
        workspace_root: Path,
        preferred_shell: str | None = None,
        columns: int = 120,
        rows: int = 28,
    ) -> None:
        self.workspace_root = workspace_root
        self.preferred_shell = preferred_shell
        self.columns = max(40, int(columns))
        self.rows = max(10, int(rows))
        self._ollama_models_dir = self._resolve_ollama_models_dir()

        self._backend = "none"
        self._active_shell = "auto"
        self._lock = threading.Lock()

        self._pty = None
        self._process: subprocess.Popen[bytes] | None = None
        self._stdout_queue: queue.Queue[str] = queue.Queue()
        self._stdout_thread: threading.Thread | None = None

    @property
    def active_shell(self) -> str:
        return self._active_shell

    def is_running(self) -> bool:
        if self._backend == "winpty" and self._pty is not None:
            try:
                return bool(self._pty.isalive())
            except Exception:
                return False
        return self._process is not None and self._process.poll() is None

    def exit_code(self) -> int | None:
        if self._backend == "winpty" and self._pty is not None:
            try:
                if self._pty.isalive():
                    return None
                return int(self._pty.get_exitstatus())
            except Exception:
                return None
        if self._process is None:
            return None
        return self._process.poll()

    def start(self) -> bool:
        with self._lock:
            if self.is_running():
                return True

            command, shell_name = self._resolve_shell_command(self.preferred_shell)
            if command is None:
                return False

            if os.name == "nt" and winpty is not None and self._start_winpty(command):
                self._active_shell = shell_name
                self._apply_shell_bootstrap()
                return True

            if self._start_subprocess(command):
                self._active_shell = shell_name
                self._apply_shell_bootstrap()
                return True

            return False

    def stop(self) -> None:
        with self._lock:
            pty = self._pty
            process = self._process
            self._pty = None
            self._process = None
            self._backend = "none"

        if pty is not None:
            try:
                pty.write("exit\r\n")
            except Exception:
                pass
            try:
                time.sleep(0.1)
                pty.cancel_io()
            except Exception:
                pass

        if process is not None:
            try:
                if process.stdin:
                    process.stdin.write(b"exit\n")
                    process.stdin.flush()
            except Exception:
                pass
            try:
                process.wait(timeout=0.8)
            except Exception:
                try:
                    process.terminate()
                except Exception:
                    pass

    def write(self, text: str) -> None:
        payload = str(text or "")
        if not payload:
            return

        if self._backend == "winpty" and self._pty is not None:
            try:
                self._pty.write(payload)
            except Exception:
                pass
            return

        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            return
        try:
            process.stdin.write(payload.encode("utf-8", errors="replace"))
            process.stdin.flush()
        except Exception:
            pass

    def read(self, timeout: float = 0.05) -> str:
        if self._backend == "winpty":
            return self._read_from_winpty(timeout)
        return self._read_from_subprocess(timeout)

    def resize(self, columns: int, rows: int) -> None:
        self.columns = max(40, int(columns))
        self.rows = max(10, int(rows))
        if self._backend == "winpty" and self._pty is not None:
            try:
                self._pty.set_size(self.columns, self.rows)
            except Exception:
                pass

    def _start_winpty(self, command: Sequence[str]) -> bool:
        if winpty is None:
            return False
        try:
            self._pty = winpty.PTY(self.columns, self.rows)
            app_name = str(command[0])
            cmdline = subprocess.list2cmdline([str(arg) for arg in command[1:]])
            self._pty.spawn(app_name, cmdline, cwd=str(self.workspace_root))
            self._backend = "winpty"
            return True
        except Exception:
            self._pty = None
            return False

    def _start_subprocess(self, command: Sequence[str]) -> bool:
        self._ollama_models_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._process = subprocess.Popen(
                [str(part) for part in command],
                cwd=str(self.workspace_root),
                env=self._build_subprocess_env(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
            )
        except Exception:
            self._process = None
            return False

        self._backend = "subprocess"
        self._stdout_thread = threading.Thread(target=self._pump_subprocess_stdout, daemon=True)
        self._stdout_thread.start()
        return True

    def _pump_subprocess_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        while True:
            try:
                chunk = process.stdout.read(self._READ_CHUNK)
            except Exception:
                break
            if not chunk:
                break
            self._stdout_queue.put(self._decode_text(chunk))

    def _read_from_subprocess(self, timeout: float) -> str:
        try:
            first = self._stdout_queue.get(timeout=max(0.0, float(timeout)))
        except queue.Empty:
            return ""
        parts = [first]
        while True:
            try:
                parts.append(self._stdout_queue.get_nowait())
            except queue.Empty:
                break
        return "".join(parts)

    def _read_from_winpty(self, timeout: float) -> str:
        pty = self._pty
        if pty is None:
            return ""
        deadline = time.monotonic() + max(0.0, float(timeout))
        parts: list[str] = []
        while True:
            try:
                chunk = pty.read(False)
            except Exception:
                chunk = ""
            text = self._decode_text(chunk)
            if text:
                parts.append(text)
                continue
            if parts or time.monotonic() >= deadline:
                break
            time.sleep(0.01)
        return "".join(parts)

    def _apply_shell_bootstrap(self) -> None:
        # Ensure winpty-backed shells inherit the workspace-local Ollama store.
        if self._backend != "winpty":
            return
        models_dir = str(self._ollama_models_dir)
        escaped = models_dir.replace('"', '""')
        commands: list[str] = []
        if self._active_shell in {"powershell", "pwsh"}:
            commands.append(
                "$utf8 = New-Object System.Text.UTF8Encoding; "
                "[Console]::OutputEncoding = $utf8; $OutputEncoding = $utf8"
            )
            commands.append(f'$env:OLLAMA_MODELS="{escaped}"')
        elif self._active_shell == "cmd":
            commands.append("chcp 65001>nul")
            commands.append(f"set OLLAMA_MODELS={models_dir}")
        elif self._active_shell in {"bash", "zsh", "sh"}:
            commands.append(f"export OLLAMA_MODELS='{models_dir}'")
        if not commands:
            return
        try:
            line_ending = "\r\n" if self._active_shell in {"powershell", "pwsh", "cmd"} else "\n"
            for command in commands:
                self.write(command + line_ending)
        except Exception:
            pass

    @staticmethod
    def _decode_text(value: bytes | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    @staticmethod
    def _normalize_shell_name(value: str | None) -> str:
        raw = str(value or "").strip().lower()
        aliases = {
            "powershell.exe": "powershell",
            "pwsh.exe": "pwsh",
            "cmd.exe": "cmd",
            "command prompt": "cmd",
        }
        return aliases.get(raw, raw)

    @classmethod
    def _resolve_shell_command(cls, preferred_shell: str | None) -> tuple[list[str] | None, str]:
        preferred = cls._normalize_shell_name(preferred_shell)

        if os.name == "nt":
            candidates: list[tuple[str, list[str]]] = [
                ("pwsh", ["pwsh", "-NoLogo", "-NoProfile"]),
                ("powershell", ["powershell", "-NoLogo", "-NoProfile"]),
                ("cmd", ["cmd"]),
                ("bash", ["bash"]),
            ]
        else:
            candidates = [
                ("bash", ["bash", "-i"]),
                ("zsh", ["zsh", "-i"]),
                ("sh", ["sh", "-i"]),
            ]

        def resolve(name: str, command: Sequence[str]) -> tuple[list[str] | None, str]:
            executable = shutil.which(str(command[0]))
            if not executable:
                return None, name
            resolved = [executable, *[str(arg) for arg in command[1:]]]
            return resolved, name

        if preferred and preferred != "auto":
            for name, command in candidates:
                if name == preferred:
                    resolved, resolved_name = resolve(name, command)
                    if resolved is not None:
                        return resolved, resolved_name

        for name, command in candidates:
            resolved, resolved_name = resolve(name, command)
            if resolved is not None:
                return resolved, resolved_name
        return None, "none"

    def _resolve_ollama_models_dir(self) -> Path:
        override = str(os.environ.get("GENESIS_OLLAMA_MODELS_DIR", "")).strip()
        if override:
            candidate = Path(override)
            if candidate.is_absolute():
                return candidate.resolve()
            return (self.workspace_root / candidate).resolve()
        return (self.workspace_root / "models/ollama").resolve()

    def _build_subprocess_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["OLLAMA_MODELS"] = str(self._ollama_models_dir)
        return env
