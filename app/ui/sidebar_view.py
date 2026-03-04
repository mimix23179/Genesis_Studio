from __future__ import annotations

from typing import Callable, Optional, Any

import butterflyui as ui


class SidebarView:
    """Conversation sidebar with reliable, explicit click binding."""

    _BG = "#F7F7F8"
    _SURFACE = "#FFFFFF"
    _BORDER = "#E5E7EB"
    _TEXT = "#202123"
    _MUTED = "#6B7280"
    _ACCENT = "#10A37F"
    _ACTIVE_BG = "#ECECF1"

    def __init__(self, width: int = 280) -> None:
        self.width = width
        self._on_new: Optional[Callable[[], None]] = None
        self._on_select: Optional[Callable[[str], None]] = None
        self._on_refresh: Optional[Callable[[], None]] = None
        self._bound_session: Any = None
        self._session_buttons: dict[str, ui.Button] = {}

        self.title = ui.Text(
            "Conversations",
            font_size=16,
            font_weight="700",
            color=self._TEXT,
        )
        self.subtitle = ui.Text(
            "Genesis memory",
            font_size=11,
            color=self._MUTED,
        )

        self.new_button = ui.Button(
            text="+  New Chat",
            variant="filled",
            events=["click"],
            bgcolor=self._ACCENT,
            text_color="#FFFFFF",
            radius=10,
            font_weight="700",
            font_size=13,
            border_color=self._ACCENT,
            border_width=1,
        )
        self.refresh_button = ui.GlyphButton(
            glyph="refresh",
            tooltip="Refresh conversations",
            events=["click"],
            color=self._TEXT,
            size="20",
        )

        self.list_column = ui.Column(spacing=4)
        self.empty_state = ui.Text(
            "No conversations yet",
            font_size=12,
            color=self._MUTED,
        )

        self._sessions: list[dict] = []
        self._active_id: str | None = None

    def on_new(self, callback: Callable[[], None]) -> None:
        self._on_new = callback

    def on_select(self, callback: Callable[[str], None]) -> None:
        self._on_select = callback

    def on_refresh(self, callback: Callable[[], None]) -> None:
        self._on_refresh = callback

    def bind_events(self, session) -> None:
        self._bound_session = session
        self.new_button.on_click(session, self._handle_new)
        self.refresh_button.on_click(session, self._handle_refresh)
        self._bind_session_buttons()

    def _bind_session_buttons(self) -> None:
        if self._bound_session is None:
            return
        for sid, button in self._session_buttons.items():
            button.on_click(
                self._bound_session,
                lambda _event=None, selected=sid: self._select(selected),
            )

    def _handle_new(self, _event=None) -> None:
        if callable(self._on_new):
            self._on_new()

    def _handle_refresh(self, _event=None) -> None:
        if callable(self._on_refresh):
            self._on_refresh()

    def set_sessions(self, sessions: list[dict], active_id: str | None = None) -> None:
        self._sessions = sessions
        self._active_id = active_id
        self._rebuild_list()

    def set_active(self, session_id: str | None) -> None:
        self._active_id = session_id
        self._rebuild_list()

    def _row_button(self, sid: str, title: str, is_active: bool) -> ui.Button:
        return ui.Button(
            text=title,
            variant="filled",
            events=["click"],
            font_size=13,
            font_weight="700" if is_active else "500",
            text_color=self._TEXT,
            bgcolor=self._ACTIVE_BG if is_active else self._SURFACE,
            border_color="#D9D9E3" if is_active else self._BORDER,
            border_width=1,
            radius=8,
            content_padding={"left": 10, "right": 10, "top": 8, "bottom": 8},
            width="100%",
        )

    def _rebuild_list(self) -> None:
        self.list_column.children.clear()
        self._session_buttons.clear()

        if not self._sessions:
            self.list_column.children.append(ui.Container(self.empty_state, padding=12))
            return

        for session in self._sessions:
            sid = str(session.get("id", "")).strip()
            if not sid:
                continue
            title = str(session.get("title", "Untitled")).strip() or "Untitled"
            is_active = sid == self._active_id
            button = self._row_button(sid, title, is_active)
            self._session_buttons[sid] = button
            row = ui.Container(
                ui.Row(ui.Text("◌", font_size=12, color=self._MUTED), button, spacing=8),
                padding={"left": 2, "right": 2},
                bgcolor=self._ACTIVE_BG if is_active else self._BG,
                radius=8,
            )
            self.list_column.children.append(row)

        self._bind_session_buttons()

    def _select(self, session_id: str) -> None:
        if callable(self._on_select):
            self._on_select(session_id)

    def build(self) -> ui.Container:
        header = ui.Container(
            ui.Column(self.title, self.subtitle, spacing=2),
            padding={"left": 16, "right": 16, "top": 16, "bottom": 8},
        )
        actions = ui.Container(
            ui.Row(self.new_button, ui.Spacer(), self.refresh_button, spacing=8),
            padding={"left": 12, "right": 12, "top": 4, "bottom": 8},
        )
        body = ui.Expanded(
            child=ui.ScrollableColumn(
                self.list_column,
                content_padding={"left": 8, "right": 8, "top": 8, "bottom": 12},
            ),
        )
        divider = ui.Divider(color=self._BORDER)
        return ui.Container(
            ui.Column(header, actions, divider, body, spacing=0, expand=True),
            width=self.width,
            bgcolor=self._BG,
            style={"border_right": f"1px solid {self._BORDER}"},
        )
