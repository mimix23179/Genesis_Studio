from __future__ import annotations

from typing import Any

import butterflyui as ui


class ChatPage:
    """Stable chat workspace built from reliable ButterflyUI primitives."""

    _BG = "#F7F7F8"
    _THREAD_BG = "#FFFFFF"
    _SURFACE = "#FFFFFF"
    _BORDER = "#D1D5DB"
    _TEXT = "#111827"
    _MUTED = "#6B7280"
    _ACCENT = "#10A37F"
    _USER_BG = "#E8F5E9"
    _ASSIST_BG = "#FFFFFF"

    def __init__(self) -> None:
        # Header
        self.title = ui.Text(
            "Genesis",
            font_size=22,
            font_weight="700",
            color=self._TEXT,
        )
        self.subtitle = ui.Text(
            "Self-contained local runtime",
            font_size=12,
            color=self._MUTED,
        )
        self.runtime_label = ui.Text(
            "Runtime: Ollama",
            font_size=12,
            font_weight="600",
            color=self._ACCENT,
        )

        # Thread
        self.chat_list = ui.ScrollableColumn(
            spacing=10,
            content_padding={"left": 12, "right": 12, "top": 12, "bottom": 12},
            expand=True,
        )
        self.typing_indicator = ui.Text(
            "Genesis is typing...",
            visible=False,
            font_size=12,
            color=self._MUTED,
            italic=True,
        )
        self._messages: list[dict[str, Any]] = []
        self._streaming_text: dict[str, str] = {}
        self._streaming_widgets: dict[str, int] = {}

        # Composer
        self._composer_value: str = ""
        self.composer = ui.TextField(
            placeholder="Message Genesis...",
            events=["change", "submit"],
            font_size=14,
            color=self._TEXT,
            dense=False,
            expand=True,
        )
        self.send_button = ui.Button(
            text="Send",
            variant="filled",
            events=["click"],
            bgcolor=self._ACCENT,
            text_color="#FFFFFF",
            radius=10,
            font_weight="700",
            border_color=self._ACCENT,
            border_width=1,
        )

        # Context + status
        self.context_switch = ui.Switch(
            value=True,
            label="Genesis source context",
            inline=True,
            events=["change"],
        )
        self.context_info = ui.Text(
            "Context: ready",
            font_size=12,
            color=self._MUTED,
        )
        self.status_text = ui.Text(
            "Idle",
            font_size=12,
            color=self._MUTED,
        )

    def build(self) -> ui.Column:
        header = ui.Surface(
            ui.Row(
                ui.Column(self.title, self.subtitle, spacing=2),
                ui.Spacer(),
                self.runtime_label,
                spacing=8,
            ),
            padding=14,
            bgcolor=self._SURFACE,
            border_color=self._BORDER,
            border_width=1,
            radius=12,
        )

        messages = ui.Expanded(
            child=ui.Container(
                ui.Column(self.chat_list, self.typing_indicator, spacing=6, expand=True),
                expand=True,
                bgcolor=self._THREAD_BG,
                radius=12,
                border_color=self._BORDER,
                border_width=1,
            )
        )

        context_row = ui.Container(
            ui.Row(self.context_switch, ui.Spacer(), self.context_info, spacing=8),
            padding={"left": 12, "right": 12, "top": 6, "bottom": 2},
        )

        composer_row = ui.Surface(
            ui.Row(self.composer, self.send_button, spacing=10, cross_axis="end"),
            padding=10,
            bgcolor=self._SURFACE,
            border_color=self._BORDER,
            border_width=1,
            radius=12,
        )

        status_row = ui.Container(
            ui.Row(self.status_text, ui.Spacer()),
            padding={"left": 12, "right": 12, "top": 2, "bottom": 6},
        )

        return ui.Column(
            ui.Container(header, padding={"left": 12, "right": 12, "top": 12, "bottom": 4}),
            messages,
            context_row,
            ui.Container(composer_row, padding={"left": 12, "right": 12, "top": 2, "bottom": 2}),
            status_row,
            spacing=0,
            expand=True,
        )

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
            return ""
        for attr in ("value", "text", "data", "message"):
            value = getattr(event, attr, None)
            if value is not None:
                return str(value)
        return ""

    def on_composer_change(self, event: Any = None) -> None:
        value = self._extract_event_text(event)
        if value:
            self._composer_value = value

    def get_composer_text(self) -> str:
        return self._composer_value.strip()

    def clear_composer(self) -> None:
        self._composer_value = ""
        try:
            self.composer.patch(value="")
        except Exception:
            pass

    def set_title(self, title: str) -> None:
        if title.strip():
            self.title.patch(text=title)

    def set_runtime_label(self, text: str) -> None:
        label = text.strip() or "Runtime: Ollama"
        self.runtime_label.patch(text=label)

    def set_status(self, status: str) -> None:
        label = status.strip() or "Idle"
        color = self._MUTED
        lowered = label.lower()
        if "error" in lowered or "fail" in lowered:
            color = "#B91C1C"
        elif "stream" in lowered or "wait" in lowered or "load" in lowered:
            color = "#1D4ED8"
        elif "ready" in lowered or "connected" in lowered:
            color = "#047857"
        self.status_text.patch(text=label, color=color)

    def set_context_info(self, text: str) -> None:
        self.context_info.patch(text=text.strip() or "Context: ready")

    def use_genesis_context(self) -> bool:
        try:
            props = self.context_switch.to_dict().get("props", {})
            return bool(props.get("value", False))
        except Exception:
            return True

    def _message_row(self, text: str, role: str) -> ui.Row:
        is_user = role == "user"
        bubble = ui.Surface(
            ui.Text(
                text,
                font_size=14,
                color=self._TEXT,
            ),
            padding={"left": 12, "right": 12, "top": 10, "bottom": 10},
            bgcolor=self._USER_BG if is_user else self._ASSIST_BG,
            border_color=self._ACCENT if is_user else self._BORDER,
            border_width=1,
            radius=12,
        )
        if is_user:
            return ui.Row(ui.Spacer(), bubble)
        return ui.Row(bubble, ui.Spacer())

    def _sync_thread(self, session=None) -> None:
        rows = [
            self._message_row(msg.get("text", ""), msg.get("role", "assistant"))
            for msg in self._messages
        ]
        self.chat_list.children.clear()
        self.chat_list.children.extend(rows)
        try:
            if session is not None:
                self.chat_list.patch(session=session, children=self.chat_list.children)
        except Exception:
            pass

    def clear_messages(self, session=None) -> None:
        self._messages.clear()
        self._sync_thread(session)
        self._streaming_text.clear()
        self._streaming_widgets.clear()
        self.typing_indicator.patch(visible=False)

    def get_messages_snapshot(self) -> list[dict[str, Any]]:
        return [dict(message) for message in self._messages]

    def restore_messages_snapshot(self, messages: list[dict[str, Any]] | None, session=None) -> None:
        self._messages = [dict(message) for message in (messages or [])]
        self._streaming_text.clear()
        self._streaming_widgets.clear()
        self.typing_indicator.patch(visible=False)
        self._sync_thread(session)

    def add_user_message(self, text: str, session=None) -> None:
        self._messages.append({"text": text, "role": "user"})
        self._sync_thread(session)

    def add_assistant_message(self, text: str, session=None) -> None:
        self._messages.append({"text": text, "role": "assistant"})
        self._sync_thread(session)

    def begin_streaming(self, message_id: str, session=None) -> None:
        if message_id in self._streaming_widgets:
            return
        self._messages.append({"id": message_id, "text": "", "role": "assistant"})
        self._streaming_widgets[message_id] = len(self._messages) - 1
        self._streaming_text[message_id] = ""
        self._sync_thread(session)
        self.typing_indicator.patch(visible=True)
        self.set_status("Streaming response...")

    def add_delta(self, message_id: str, delta: str, session=None) -> None:
        if message_id not in self._streaming_text:
            return
        self._streaming_text[message_id] += delta or ""
        message_index = self._streaming_widgets.get(message_id)
        if isinstance(message_index, int) and 0 <= message_index < len(self._messages):
            self._messages[message_index]["text"] = self._streaming_text[message_id]
            self._sync_thread(session)

    def finalize_stream(self, message_id: str, full_text: str, session=None) -> None:
        self._streaming_text.pop(message_id, None)
        message_index = self._streaming_widgets.pop(message_id, None)
        if isinstance(message_index, int) and 0 <= message_index < len(self._messages):
            self._messages[message_index]["text"] = full_text
            self._sync_thread(session)
        else:
            self.add_assistant_message(full_text, session)
        self.typing_indicator.patch(visible=len(self._streaming_widgets) > 0)
        self.set_status("Idle")
