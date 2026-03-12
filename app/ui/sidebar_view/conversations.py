from __future__ import annotations

from typing import Any, Callable, Optional

import butterflyui as ui


class Conversations:
    """Conversation sidebar with reliable, explicit click binding."""

    _BG = "#F7F7F8"
    _SURFACE = "#FFFFFF"
    _BORDER = "#E5E7EB"
    _TEXT = "#0F172A"
    _MUTED = "#475569"
    _ACCENT = "#10A37F"
    _ACTIVE_BG = "#DCE6FF"
    _ACTIVE_TEXT = "#0B1220"
    _ACTIVE_BORDER = "#D9D9E3"
    _ON_ACCENT = "#FFFFFF"

    def __init__(self, width: int = 280) -> None:
        self.width = width
        self._glass_mode = False
        self._root_container: ui.Container | None = None
        self._list_host: ui.Container | None = None
        self._on_new: Optional[Callable[[], None]] = None
        self._on_select: Optional[Callable[[str], None]] = None
        self._on_refresh: Optional[Callable[[], None]] = None
        self._bound_session: Any = None
        self._session_cards: dict[str, ui.ArtifactCard] = {}

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
            class_name="gs-button gs-primary",
            variant="filled",
            events=["click"],
            radius=10,
            font_weight="700",
            font_size=13,
        )
        self.refresh_button = ui.GlyphButton(
            glyph="refresh",
            tooltip="Refresh conversations",
            events=["click"],
            color=self._TEXT,
            size="20",
        )

        self.list_column = ui.ScrollableColumn(
            spacing=10,
            expand=True,
            content_padding={"left": 8, "right": 8, "top": 8, "bottom": 12},
        )
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
        self._bind_session_cards()

    def _bind_session_cards(self) -> None:
        if self._bound_session is None:
            return
        for sid, card in self._session_cards.items():
            card.on_tap(self._bound_session, lambda _event=None, selected=sid: self._select(selected))
            card.on_event(self._bound_session, "action", lambda _event=None, selected=sid: self._select(selected))

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

    def _row_card(self, session: dict[str, Any], is_active: bool) -> ui.ArtifactCard:
        title = str(session.get("title", "Untitled")).strip() or "Untitled"
        preview = str(session.get("preview", "")).strip() or "New conversation"
        active_model = str(session.get("active_model", "")).strip()
        count = str(session.get("message_count", "0")).strip() or "0"
        meta = ui.Column(
            ui.Text(
                active_model or "No model selected",
                font_size=11,
                color=self._ACCENT if is_active else self._MUTED,
                font_weight="600",
            ),
            ui.Text(
                f"{count} messages",
                font_size=11,
                color=self._MUTED,
            ),
            spacing=3,
        )
        return ui.ArtifactCard(
            meta,
            title=title,
            class_name="gs-session-item-active" if is_active else "gs-session-item",
            label="Active" if is_active else "Saved",
            message=preview,
            action_label="Open",
            clickable=True,
            events=["click", "action"],
        )

    def _rebuild_list(self) -> None:
        self.list_column.children.clear()
        self._session_cards.clear()

        if not self._sessions:
            self.list_column.children.append(ui.Container(self.empty_state, padding=12))
            return

        for session in self._sessions:
            sid = str(session.get("id", "")).strip()
            if not sid:
                continue
            is_active = sid == self._active_id
            card = self._row_card(session, is_active)
            self._session_cards[sid] = card
            self.list_column.children.append(card)

        self._bind_session_cards()

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
        self._list_host = ui.Container(
            self.list_column,
            expand=True,
            padding={"left": 0, "right": 0, "top": 0, "bottom": 0},
        )
        self._root_container = ui.Container(
            ui.Column(header, actions, ui.Expanded(self._list_host), spacing=0, expand=True),
            width=self.width,
            class_name="gs-sidebar",
            style={"border_right": f"1px solid {self._BORDER}"},
        )
        return self._root_container

    def set_glass_mode(self, enabled: bool) -> None:
        self._glass_mode = bool(enabled)
        self._rebuild_list()

    def set_palette(self, palette: dict[str, str]) -> None:
        self._BG = palette.get("bg", self._BG)
        self._SURFACE = palette.get("surface", self._SURFACE)
        self._BORDER = palette.get("border", self._BORDER)
        self._TEXT = palette.get("text", self._TEXT)
        self._MUTED = palette.get("muted", self._MUTED)
        self._ACCENT = palette.get("accent", self._ACCENT)
        self._ACTIVE_BG = palette.get("active_bg", self._ACTIVE_BG)
        self._ACTIVE_TEXT = palette.get("active_text", self._ACTIVE_TEXT)
        self._ACTIVE_BORDER = palette.get("active_border", self._ACTIVE_BORDER)
        self._ON_ACCENT = palette.get("on_accent", self._ON_ACCENT)

        try:
            self.title.patch(color=self._TEXT)
            self.subtitle.patch(color=self._MUTED)
            self.refresh_button.patch(color=self._TEXT)
        except Exception:
            pass

        if self._glass_mode:
            self.set_glass_mode(True)
        else:
            self._rebuild_list()

    def set_accent(self, color: str) -> None:
        self._ACCENT = str(color or "").strip() or self._ACCENT
