from __future__ import annotations

from typing import Callable, Optional

import butterflyui as ui


class SidebarView:
	"""Conversation sidebar — polished card-based list with reliable event binding."""

	_BG        = "#F3F4F6"
	_SURFACE   = "#FFFFFF"
	_BORDER    = "#C5C5C5"
	_TEXT      = "#1A1A2E"
	_MUTED     = "#6B7280"
	_ACCENT    = "#6366F1"
	_ACTIVE_BG = "#EEF2FF"

	def __init__(self, width: int = 280) -> None:
		self.width = width
		self._on_new: Optional[Callable[[], None]] = None
		self._on_select: Optional[Callable[[str], None]] = None
		self._on_refresh: Optional[Callable[[], None]] = None

		self.title = ui.Text(
			"Conversations",
			style={"font_size": "16", "font_weight": "700", "color": "self._TEXT"},
		)
		self.subtitle = ui.Text(
			"Genesis memory",
			style={"font_size": "11", "color": "self._MUTED"},
		)

		self.new_button = ui.Button(
			text="＋  New Chat", variant="filled", events=["click"],
			style={"border_radius": "10", "background": "self._ACCENT", "color": "self._TEXT", "font_weight": "600", "font_size": "13"},
		)
		self.refresh_button = ui.GlyphButton(
			glyph="refresh", tooltip="Refresh conversations", events=["click"],
			color="self._MUTED", size="20",
		)

		self.list_column = ui.Column(spacing="4")
		self.empty_state = ui.Text(
			"No conversations yet",
			style={"font_size": "12", "color": "self._MUTED"},
		)

		self._sessions: list[dict] = []
		self._active_id: str | None = None

	# ── Public callbacks ────────────────────────────────────────────

	def on_new(self, callback: Callable[[], None]) -> None:
		self._on_new = callback

	def on_select(self, callback: Callable[[str], None]) -> None:
		self._on_select = callback

	def on_refresh(self, callback: Callable[[], None]) -> None:
		self._on_refresh = callback

	def bind_events(self, session) -> None:
		"""Explicitly bind button click events to the live session."""
		self.new_button.on_click(session, self._handle_new)
		self.refresh_button.on_click(session, self._handle_refresh)

	# ── Internal handlers ───────────────────────────────────────────

	def _handle_new(self, event=None) -> None:
		if callable(self._on_new):
			self._on_new()

	def _handle_refresh(self, event=None) -> None:
		if callable(self._on_refresh):
			self._on_refresh()

	# ── Session list management ─────────────────────────────────────

	def set_sessions(self, sessions: list[dict], active_id: str | None = None) -> None:
		self._sessions = sessions
		self._active_id = active_id
		self._rebuild_list()

	def set_active(self, session_id: str | None) -> None:
		self._active_id = session_id
		self._rebuild_list()

	def _rebuild_list(self) -> None:
		self.list_column.children.clear()

		if not self._sessions:
			self.list_column.children.append(
				ui.Container(self.empty_state, padding=12),
			)
			return

		for session in self._sessions:
			sid = str(session.get("id", "")).strip()
			if not sid:
				continue
			title = str(session.get("title", "Untitled")).strip() or "Untitled"
			is_active = sid == self._active_id

			card = ui.Surface(
				ui.Row(
					ui.Text("💬", style={"font_size": 14}),
					ui.Text(
						title,
						style={
							"font_size": "13",
							"font_weight": 600 if is_active else 400,
							"color": "self._ACCENT" if is_active else "self._TEXT",
						},
					),
					spacing=8,
				),
				padding="10",
				radius="10",
				bgcolor="self._ACTIVE_BG" if is_active else "self._SURFACE",
				border_color="self._ACCENT" if is_active else "self._BORDER",
				border_width=1,
			)
			# Wrap in a Pressable so the whole card is tappable
			pressable = ui.Pressable(
				card,
				events=["click"],
				on_click=lambda e=None, selected=sid: self._select(selected),
				style={"cursor": "pointer"},
			)
			self.list_column.children.append(ui.Container(pressable, padding={"left": 2, "right": 2}))

	def _select(self, session_id: str) -> None:
		if callable(self._on_select):
			self._on_select(session_id)

	# ── Layout ──────────────────────────────────────────────────────

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
				padding={"left": 8, "right": 8},
			),
		)

		divider = ui.Divider(color=self._BORDER)

		return ui.Container(
			ui.Column(header, actions, divider, body, spacing=0, expand=True),
			width=self.width,
			bgcolor="self._BG",
			style={"border_right": f"1px solid {self._BORDER}"},
		)
