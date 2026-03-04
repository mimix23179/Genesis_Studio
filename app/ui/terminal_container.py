from __future__ import annotations

from typing import Any, Callable

import butterflyui as ui

from app.config import AppPaths


class TerminalContainer:
    """Native ButterflyUI terminal panel with keyboard capture."""

    _SURFACE = "#0B0F14"
    _SURFACE_ALT = "#111827"
    _BORDER = "#1F2937"
    _TEXT = "#E5E7EB"
    _MUTED = "#9CA3AF"
    _ACCENT = "#10A37F"
    _MAX_BUFFER = 240000

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self._session = None
        self._pending_input = ""
        self._stream_output = ""
        self._screen_text = ""
        self._on_command: Callable[[str], None] | None = None
        self._on_shell_change: Callable[[str], None] | None = None
        self._on_clear: Callable[[], None] | None = None
        self._on_restart: Callable[[], None] | None = None
        self._on_key_event: Callable[[Any], None] | None = None

        self.title = ui.Text("Terminal", font_size=13, font_weight="700", color=self._TEXT)
        self.status = ui.Text("Ready", font_size=11, color=self._MUTED)
        self.shell_select = ui.Select(
            label="Shell",
            value="auto",
            options=[
                {"label": "Auto", "value": "auto"},
                {"label": "PowerShell 7 (pwsh)", "value": "pwsh"},
                {"label": "Windows PowerShell", "value": "powershell"},
                {"label": "Command Prompt (cmd)", "value": "cmd"},
                {"label": "Bash", "value": "bash"},
                {"label": "Zsh", "value": "zsh"},
                {"label": "Sh", "value": "sh"},
            ],
            events=["change"],
            width=220,
        )
        self.clear_button = ui.Button(
            text="Clear",
            variant="outlined",
            events=["click"],
            radius=8,
            border_width=1,
            border_color=self._BORDER,
            text_color=self._TEXT,
            bgcolor=self._SURFACE_ALT,
        )
        self.restart_button = ui.Button(
            text="Restart",
            variant="outlined",
            events=["click"],
            radius=8,
            border_width=1,
            border_color=self._BORDER,
            text_color=self._TEXT,
            bgcolor=self._SURFACE_ALT,
        )
        self.output_text = ui.Text(
            "",
            font_family="monospace",
            font_size=12,
            color=self._TEXT,
            selectable=True,
        )
        self.output_view = ui.ScrollableColumn(
            self.output_text,
            expand=True,
            content_padding={"left": 10, "right": 10, "top": 10, "bottom": 10},
        )
        self.output_keys = ui.KeyListener(
            self.output_view,
            autofocus=True,
            enabled=True,
            events=["key_down", "key_repeat"],
        )
        self.command_input = ui.TextField(
            placeholder="Enter command and press Enter",
            events=["change", "submit"],
            expand=True,
            font_family="monospace",
        )
        self.send_button = ui.Button(
            text="Run",
            variant="filled",
            events=["click"],
            bgcolor=self._ACCENT,
            text_color="#FFFFFF",
            border_color=self._ACCENT,
            border_width=1,
            radius=8,
            font_weight="700",
        )

    def build(self):
        header = ui.Surface(
            ui.Row(
                ui.Column(self.title, self.status, spacing=2),
                ui.Spacer(),
                self.shell_select,
                self.clear_button,
                self.restart_button,
                spacing=8,
                cross_axis="end",
            ),
            padding={"left": 10, "right": 10, "top": 8, "bottom": 8},
            bgcolor=self._SURFACE_ALT,
            border_color=self._BORDER,
            border_width=1,
            radius=10,
        )
        output = ui.Surface(
            self.output_keys,
            expand=True,
            bgcolor=self._SURFACE,
            border_color=self._BORDER,
            border_width=1,
            radius=10,
        )
        composer = ui.Surface(
            ui.Row(self.command_input, self.send_button, spacing=8, cross_axis="end"),
            padding={"left": 10, "right": 10, "top": 8, "bottom": 8},
            bgcolor=self._SURFACE_ALT,
            border_color=self._BORDER,
            border_width=1,
            radius=10,
        )
        return ui.Container(
            ui.Column(header, output, composer, spacing=8, expand=True),
            padding={"left": 10, "right": 10, "top": 8, "bottom": 8},
            bgcolor=self._SURFACE,
            expand=True,
        )

    def bind_events(
        self,
        session,
        *,
        on_command: Callable[[str], None],
        on_shell_change: Callable[[str], None] | None = None,
        on_clear: Callable[[], None] | None = None,
        on_restart: Callable[[], None] | None = None,
        on_key_event: Callable[[Any], None] | None = None,
    ) -> None:
        self._session = session
        self._on_command = on_command
        self._on_shell_change = on_shell_change
        self._on_clear = on_clear
        self._on_restart = on_restart
        self._on_key_event = on_key_event

        self.command_input.on_change(session, self._on_command_change, inputs=[self.command_input])
        self.command_input.on_submit(session, self._on_command_submit)
        self.send_button.on_click(session, self._on_send_click)
        self.shell_select.on_change(session, self._on_shell_select_change, inputs=[self.shell_select])
        self.clear_button.on_click(session, self._on_clear_click)
        self.restart_button.on_click(session, self._on_restart_click)
        self.output_keys.on_key_down(session, self._on_key_down)
        self.output_keys.on_event(session, "key_repeat", self._on_key_repeat)

    def attach_event_handler(self, session, callback) -> None:
        # Backward-compat no-op: terminal handlers are bound explicitly in bind_events().
        _ = session
        _ = callback

    def open(self, session) -> None:
        try:
            self.output_keys.request_focus(session)
        except Exception:
            pass

    def close(self, session) -> None:
        _ = session

    def set_shell(self, value: str) -> None:
        target = str(value or "auto").strip() or "auto"
        try:
            self.shell_select.patch(value=target)
        except Exception:
            pass

    def set_status(self, text: str) -> None:
        self.status.patch(text=str(text).strip() or "Ready")

    def clear_output(self) -> None:
        self._stream_output = ""
        self._screen_text = ""
        self.output_text.patch(text="")

    def render_screen(self, session, text: str) -> None:
        _ = session
        self._screen_text = str(text or "")
        self._refresh_output()

    def send_output(self, session, text: str) -> None:
        _ = session
        payload = str(text or "")
        if not payload:
            return
        self._stream_output += payload
        if len(self._stream_output) > self._MAX_BUFFER:
            self._stream_output = self._stream_output[-self._MAX_BUFFER :]
        self._refresh_output()

    def _refresh_output(self) -> None:
        combined = self._compose_output()
        self.output_text.patch(text=combined)
        session = self._session
        if session is not None:
            try:
                self.output_view.scroll_to_end(session, animate=False)
            except Exception:
                pass

    def _compose_output(self) -> str:
        if self._stream_output and self._screen_text:
            separator = "" if self._stream_output.endswith(("\n", "\r")) else "\n"
            return f"{self._stream_output}{separator}{self._screen_text}"
        return self._screen_text or self._stream_output

    def _on_command_change(self, value=None, event=None) -> None:
        _ = event
        if value is None:
            value = self._read_control_value(self.command_input, "")
        self._pending_input = str(value or "")

    def _on_command_submit(self, event=None) -> None:
        self._emit_command(self._extract_event_text(event))

    def _on_send_click(self, event=None) -> None:
        _ = event
        self._emit_command("")

    def _on_shell_select_change(self, value=None, event=None) -> None:
        _ = event
        selected = str(value if value is not None else self._read_control_value(self.shell_select, "auto")).strip()
        if not selected:
            selected = "auto"
        self.shell_select.patch(value=selected)
        if callable(self._on_shell_change):
            self._on_shell_change(selected)

    def _on_clear_click(self, event=None) -> None:
        _ = event
        self.clear_output()
        if callable(self._on_clear):
            self._on_clear()

    def _on_restart_click(self, event=None) -> None:
        _ = event
        if callable(self._on_restart):
            self._on_restart()

    def _on_key_down(self, event=None) -> None:
        self._forward_key(event)

    def _on_key_repeat(self, event=None) -> None:
        self._forward_key(event)

    def _forward_key(self, event: Any) -> None:
        if callable(self._on_key_event):
            self._on_key_event(event)

    def _emit_command(self, proposed: str) -> None:
        text = str(proposed or "").strip()
        if not text:
            text = str(self._read_control_value(self.command_input, self._pending_input)).strip()
        if not text:
            return
        self._pending_input = ""
        self.command_input.patch(value="")
        if callable(self._on_command):
            self._on_command(text)

    def _extract_event_text(self, event: Any) -> str:
        if event is None:
            return ""
        if isinstance(event, dict):
            payload = event.get("payload")
            if isinstance(payload, dict):
                value = payload.get("value", payload.get("text", payload.get("data")))
                if value is not None:
                    return str(value)
            for key in ("value", "text", "data", "message"):
                if event.get(key) is not None:
                    return str(event.get(key))
        for attr in ("value", "text", "data", "message"):
            value = getattr(event, attr, None)
            if value is not None:
                return str(value)
        return ""

    def _read_control_value(self, control: Any, fallback: str) -> str:
        session = self._session
        if session is not None:
            try:
                value = session.get_value(control, prop="value")
                if value is not None:
                    return str(value)
            except Exception:
                pass
        try:
            props = control.to_dict().get("props", {})
            return str(props.get("value", fallback))
        except Exception:
            return str(fallback)
