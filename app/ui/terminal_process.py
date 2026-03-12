from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from genesis.backend.terminal import TerminalEmulator, TerminalSession


class TerminalProcess:
    """Terminal orchestration: PTY session + ANSI emulator + key mapping."""

    _DEFAULT_COLS = 180
    _DEFAULT_ROWS = 28

    def __init__(
        self,
        *,
        workspace_root: Path,
        on_output: Callable[[str], None] | None = None,
        on_screen: Callable[[str], None] | None = None,
        on_closed: Callable[[int | None], None] | None = None,
        preferred_shell: str | None = None,
    ) -> None:
        self.workspace_root = workspace_root
        self.preferred_shell = preferred_shell
        self.on_output = on_output
        self.on_screen = on_screen
        self.on_closed = on_closed

        self._session: TerminalSession | None = None
        self._emulator = TerminalEmulator(columns=self._DEFAULT_COLS, rows=self._DEFAULT_ROWS, history=2500)
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._last_frame = ""

    @property
    def active_shell(self) -> str:
        if self._session is None:
            return "none"
        return self._session.active_shell

    def is_running(self) -> bool:
        return self._session is not None and self._session.is_running()

    def start(self) -> bool:
        with self._lock:
            if self.is_running():
                return True

            self._stop_event.clear()
            self._emulator.reset()
            self._last_frame = ""
            session = TerminalSession(
                workspace_root=self.workspace_root,
                preferred_shell=self.preferred_shell,
                columns=self._DEFAULT_COLS,
                rows=self._DEFAULT_ROWS,
            )
            if not session.start():
                self._session = None
                if callable(self.on_output):
                    self.on_output("\r\nNo supported shell was found on this machine.\r\n")
                return False

            self._session = session
            self._reader = threading.Thread(target=self._pump_output, daemon=True)
            self._reader.start()
            self._emit_screen()
            return True

    def restart(self, preferred_shell: str | None = None) -> bool:
        if preferred_shell is not None:
            self.preferred_shell = preferred_shell
        self.stop()
        return self.start()

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            session = self._session
            self._session = None
        if session is not None:
            session.stop()

    def resize(self, *, columns: int, rows: int) -> None:
        if self._session is not None:
            self._session.resize(columns, rows)
        self._emulator.resize(columns=columns, rows=rows)
        self._emit_screen()

    def clear_render(self) -> None:
        self._emulator.reset()
        self._emit_screen(force=True)

    def inject_output(self, text: str) -> None:
        payload = str(text or "")
        if not payload:
            return
        self._emulator.feed(payload.replace("\r\n", "\n"))
        self._emit_screen(force=True)

    def write_line(self, command: str) -> None:
        text = str(command or "").rstrip("\r\n")
        if not text:
            return
        self.write_input(text + "\r")

    def write_input(self, text: str) -> None:
        session = self._session
        if session is None or not session.is_running():
            if callable(self.on_output):
                self.on_output("\r\nTerminal process is not running.\r\n")
            return
        session.write(text)

    def send_key_event(self, event: Any) -> None:
        sequence = self._map_key_event(event)
        if sequence:
            self.write_input(sequence)

    def _pump_output(self) -> None:
        session = self._session
        if session is None:
            return
        exit_code: int | None = None
        try:
            while not self._stop_event.is_set():
                chunk = session.read(timeout=0.05)
                if chunk:
                    if callable(self.on_output):
                        self.on_output(chunk)
                    self._emulator.feed(chunk)
                    self._emit_screen()
                    continue
                if not session.is_running():
                    break
        finally:
            exit_code = session.exit_code()
            if self._session is session:
                self._session = None
            if callable(self.on_closed):
                self.on_closed(exit_code)

    def _emit_screen(self, *, force: bool = False) -> None:
        if not callable(self.on_screen):
            return
        frame = self._emulator.render()
        if force or frame != self._last_frame:
            self._last_frame = frame
            self.on_screen(frame)

    @staticmethod
    def _normalize_key_name(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        if "." in raw:
            raw = raw.rsplit(".", maxsplit=1)[-1]
        lowered = raw.lower().replace(" ", "")
        aliases = {
            "arrowup": "up",
            "arrowdown": "down",
            "arrowleft": "left",
            "arrowright": "right",
            "return": "enter",
            "esc": "escape",
            "spacebar": "space",
            "backspace": "backspace",
            "del": "delete",
            "pgup": "pageup",
            "pgdn": "pagedown",
        }
        return aliases.get(lowered, lowered)

    @staticmethod
    def _extract_key_payload(event: Any) -> tuple[str, set[str]]:
        payload: dict[str, Any] = {}
        if isinstance(event, dict):
            maybe_payload = event.get("payload")
            if isinstance(maybe_payload, dict):
                payload = maybe_payload
            else:
                payload = event
        else:
            maybe_payload = getattr(event, "payload", None)
            if isinstance(maybe_payload, dict):
                payload = maybe_payload
            elif isinstance(event, object):
                payload = {
                    "key": getattr(event, "key", None),
                    "modifiers": getattr(event, "modifiers", None),
                }

        key = TerminalProcess._normalize_key_name(
            payload.get("key")
            or payload.get("logical_key")
            or payload.get("code")
            or payload.get("value")
        )
        raw_modifiers = payload.get("modifiers", [])
        if not isinstance(raw_modifiers, (list, tuple, set)):
            raw_modifiers = [raw_modifiers]
        modifiers = {str(item).strip().lower() for item in raw_modifiers if str(item).strip()}
        return key, modifiers

    @classmethod
    def _map_key_event(cls, event: Any) -> str:
        key, modifiers = cls._extract_key_payload(event)
        if not key:
            return ""

        ctrl = "control" in modifiers or "ctrl" in modifiers
        alt = "alt" in modifiers
        shift = "shift" in modifiers

        special = {
            "enter": "\r",
            "tab": "\t",
            "escape": "\x1b",
            "backspace": "\x7f",
            "delete": "\x1b[3~",
            "up": "\x1b[A",
            "down": "\x1b[B",
            "right": "\x1b[C",
            "left": "\x1b[D",
            "home": "\x1b[H",
            "end": "\x1b[F",
            "pageup": "\x1b[5~",
            "pagedown": "\x1b[6~",
        }
        if key in special:
            return special[key]

        if ctrl and len(key) == 1 and "a" <= key <= "z":
            return chr(ord(key) - ord("a") + 1)

        if key == "space":
            value = " "
        elif len(key) == 1:
            value = key.upper() if shift else key
        else:
            return ""

        if alt:
            return "\x1b" + value
        return value
