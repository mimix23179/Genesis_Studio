"""Chat page built entirely with native ButterflyUI components.

Uses ChatThread, ChatMessage, TypingIndicator, and MessageComposer
instead of raw Column+Text widgets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional

import butterflyui as ui


@dataclass
class ChatPage:
    page: ui.Page
    paths: object

    def __post_init__(self) -> None:
        self._on_send: Optional[Callable[[Optional[str]], None]] = None
        self._on_toggle_terminal: Optional[Callable[[], None]] = None

        # Header
        self.title = ui.Text("New Conversation", style={"font_size": 20, "font_weight": 700})

        # Chat thread — native ButterflyUI component
        self.chat_thread = ui.ChatThread(expand=True)

        # Typing indicator — shown when the brain is streaming
        self.typing_indicator = ui.TypingIndicator(visible=False)

        # Composer
        self.composer = ui.TextArea(
            placeholder="Ask Genesis Studio...",
            min_lines=2,
            max_lines=6,
            expand=True,
        )
        self.send_btn = ui.Button(
            text="Send 💬",
            variant="filled",
            on_click=self._handle_send,
            width=120,
        )

        # Terminal slot — injectable Column where the terminal HtmlView attaches
        self.terminal_slot = ui.Column()
        self.terminal_visible = False

        # Streaming state: message_id -> accumulated text
        self._streaming: Dict[str, str] = {}
        self._streaming_widgets: Dict[str, ui.ChatMessage] = {}

    # ── Event Handlers ───────────────────────────────────────────────

    def _handle_send(self, event=None) -> None:
        text = getattr(self.composer, "value", None) or getattr(self.composer, "text", None)
        if callable(self._on_send):
            try:
                self._on_send(text)
            except Exception:
                pass

    def _handle_toggle(self, event=None) -> None:
        if callable(self._on_toggle_terminal):
            try:
                self._on_toggle_terminal()
            except Exception:
                pass

    # ── Public API ───────────────────────────────────────────────────

    def on_send(self, callback: Callable[[Optional[str]], None]) -> None:
        self._on_send = callback

    def on_toggle_terminal(self, callback: Callable[[], None]) -> None:
        self._on_toggle_terminal = callback

    def build(self) -> ui.Column:
        composer_row = ui.Container(
            ui.Row(
                ui.Expanded(child=self.composer),
                ui.Column(ui.Row(self.send_btn)),
            ),
            padding=12,
        )
        header = ui.Container(
            ui.Row(self.title, ui.Spacer()),
            padding=8,
        )
        # Terminal slot placed below composer so it appears from the bottom
        terminal_container = ui.Container(self.terminal_slot, padding=0)

        return ui.Column(
            header,
            ui.Expanded(child=ui.Container(
                ui.Column(self.chat_thread, self.typing_indicator, spacing=4, expand=True),
                padding=8,
            )),
            composer_row,
            terminal_container,
            spacing=12,
            expand=True,
        )

    # ── Message Management ───────────────────────────────────────────

    def add_user_message(self, text: str) -> None:
        """Add a user message bubble to the chat thread."""
        msg = ui.ChatMessage(
            text=text,
            sender="user",
            alignment="end",
        )
        self.chat_thread.children.append(msg)

    def add_assistant_message(self, text: str) -> None:
        """Add a finalized assistant message bubble."""
        msg = ui.ChatMessage(
            text=text,
            sender="assistant",
            alignment="start",
        )
        self.chat_thread.children.append(msg)

    def begin_streaming(self, message_id: str) -> None:
        """Show typing indicator when streaming begins."""
        self._streaming[message_id] = ""
        bubble = ui.ChatMessage(
            text="",
            sender="assistant",
            alignment="start",
        )
        self._streaming_widgets[message_id] = bubble
        self.chat_thread.children.append(bubble)
        self.typing_indicator.visible = True

    def add_delta(self, message_id: str, delta: str) -> None:
        """Accumulate streaming text for a message."""
        if message_id in self._streaming:
            self._streaming[message_id] += delta
            bubble = self._streaming_widgets.get(message_id)
            if bubble is not None:
                try:
                    bubble.text = self._streaming[message_id]
                except Exception:
                    try:
                        bubble.value = self._streaming[message_id]
                    except Exception:
                        pass

    def finalize_message(self, message_id: str, full_text: str) -> None:
        """Replace streaming state with the finalized assistant message."""
        self._streaming.pop(message_id, None)
        bubble = self._streaming_widgets.pop(message_id, None)
        if bubble is not None:
            try:
                bubble.text = full_text
            except Exception:
                try:
                    bubble.value = full_text
                except Exception:
                    pass
        elif full_text:
            self.add_assistant_message(full_text)
        self.typing_indicator.visible = len(self._streaming) > 0

    def clear_composer(self) -> None:
        """Clear the composer text area after sending."""
        try:
            self.composer.value = ""
        except Exception:
            pass

    def set_title(self, title: str) -> None:
        self.title.value = title

    # ── Terminal Slot ────────────────────────────────────────────────

    def attach_terminal(self, view: ui.HtmlView) -> None:
        if view is None:
            return
        self.terminal_slot.children.clear()
        self.terminal_slot.children.append(view)
        self.terminal_visible = True

    def detach_terminal(self) -> None:
        self.terminal_slot.children.clear()
        self.terminal_visible = False

    def toggle_terminal(self, view: ui.HtmlView | None = None) -> None:
        if self.terminal_visible:
            self.detach_terminal()
        else:
            if view is not None:
                self.attach_terminal(view)
