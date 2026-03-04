from __future__ import annotations

from typing import Iterable

import pyte
from wcwidth import wcswidth


class TerminalEmulator:
    """ANSI/VT100 emulator backed by pyte with bounded scrollback rendering."""

    def __init__(self, *, columns: int = 120, rows: int = 28, history: int = 2000) -> None:
        self.columns = max(40, int(columns))
        self.rows = max(10, int(rows))
        self.history = max(100, int(history))

        self.screen = pyte.HistoryScreen(self.columns, self.rows, history=self.history)
        self.stream = pyte.Stream(self.screen)

    def feed(self, text: str) -> None:
        payload = str(text or "")
        if payload:
            self.stream.feed(payload)

    def reset(self) -> None:
        self.screen.reset()

    def resize(self, *, columns: int, rows: int) -> None:
        self.columns = max(40, int(columns))
        self.rows = max(10, int(rows))
        self.screen.resize(lines=self.rows, columns=self.columns)

    def render(self) -> str:
        history_top: list[str] = list(getattr(self.screen.history, "top", []))
        visible: list[str] = list(self.screen.display)
        lines = history_top + visible
        if len(lines) > self.history:
            lines = lines[-self.history :]
        normalized = [self._normalize_line(line) for line in lines]
        while normalized and not normalized[-1]:
            normalized.pop()
        return "\n".join(normalized)

    @staticmethod
    def _normalize_line(line: str) -> str:
        # pyte may retain trailing spaces; keep user text but drop terminal pad.
        text = str(line or "").replace("\x00", "")
        if not text:
            return ""
        trimmed = text.rstrip()
        if not trimmed:
            return ""
        # wcwidth < 0 means non-printable codepoints; strip them for stable output.
        if wcswidth(trimmed) < 0:
            return "".join(ch for ch in trimmed if ch.isprintable() or ch in "\t ")
        return trimmed

    def snapshot_lines(self) -> Iterable[str]:
        rendered = self.render()
        return rendered.splitlines()
