from __future__ import annotations

import time
from typing import Any, Dict

import butterflyui as ui


class ChatPage:
	"""Chat workspace — polished layout built entirely from ButterflyUI controls.

	Exposes the ``composer`` (MessageComposer with built-in send button),
	streaming helpers, and context-toggle switch. All interactive controls carry
	``events=[…]`` so the Flutter runtime subscribes immediately; the shell
	then calls ``.on_submit(session, handler)`` etc. for explicit binding.
	"""

	# ── Colour tokens ──────────────────────────────────────────────
	_BG          = "#F8F9FB"
	_SURFACE     = "#FFFFFF"
	_BORDER      = "#C5C5C5"
	_TEXT         = "#1A1A2E"
	_MUTED        = "#6B7280"
	_ACCENT       = "#6366F1"
	_ACCENT_LIGHT = "#5078FF"

	def __init__(self) -> None:
		# ── Header ──
		self.title = ui.Text(
			"Genesis",
			style={"font_size": "22", "font_weight": "700", "color": "self._TEXT"},
		)
		self.subtitle = ui.Text(
			"Self-contained local runtime",
			style={"font_size": "12", "color": "self._MUTED"},
		)

		# ── Chat thread ──
		self.chat_thread = ui.ChatThread(
			messages=[],
			expand=True, auto_scroll=True, spacing=10, group_messages=True,
			style={"padding": "12"},
		)
		self.typing_indicator = ui.TypingIndicator(visible=False)
		self._messages: list[dict[str, Any]] = []

		# ── Composer area ──
		self._composer_value: str = ""
		self.composer = ui.MessageComposer(
			placeholder="Message Genesis…",
			send_label="Send",
			clear_on_send=True,
			emit_on_change=True,
			min_lines=1,
			max_lines=4,
			events=["submit", "change", "send"],
			style={
				"font_size": "14",
				"border_radius": "12",
				"border_color": "self._BORDER",
				"background": "self._SURFACE",
			},
		)

		# ── Context toggle ──
		self.context_switch = ui.Switch(
			value=True, 
			label="Genesis source context", 
			inline=True,
			events=["change"],
		)
		self.context_info = ui.Text(
			"Context: ready",
			style={"font_size": "11", "color": "self._MUTED"},
		)

		# ── Status bar ──
		self.status_text = ui.Text(
			"Idle",
			style={"font_size": "11", "color": "self._MUTED"},
		)

		# ── Streaming state ──
		self._streaming_text: Dict[str, str] = {}
		self._streaming_widgets: Dict[str, Any] = {}

	# ── Layout ──────────────────────────────────────────────────────

	def build(self) -> ui.Column:
		header = ui.Surface(
			ui.Row(
				ui.Column(self.title, self.subtitle, spacing=2),
				ui.Spacer(),
				ui.Text(
					"●",
					style={"font_size": "10", "color": "self._ACCENT"},
				),
				spacing=8,
			),
			padding="16", 
			bgcolor="self._SURFACE",
			border_color="self._BORDER", 
			border_width="1", 
			radius="14",
		)

		messages = ui.Container(
			ui.Column(self.chat_thread, self.typing_indicator, spacing=6, expand=True),
			expand=True,
			style={"background": "self._BG", "border_radius": "12"},
		)

		context_row = ui.Container(
			ui.Row(self.context_switch, ui.Spacer(), self.context_info, spacing=8),
			padding={"left": "12", "right": "12", "top": "6", "bottom": "2"},
		)

		composer_row = ui.Surface(
			self.composer,
			padding="10", 
			bgcolor="self._SURFACE",
			border_color="self._BORDER", 
			border_width="1", 
			radius="14",
		)

		status_bar = ui.Container(
			ui.Row(self.status_text, ui.Spacer()),
			padding={"left": "12", "right": "12", "top": "2", "bottom": "6"},
		)

		return ui.Column(
			ui.Container(header, padding={"left": "12", "right": "12", "top": "12", "bottom": "4"}),
			messages,
			context_row,
			ui.Container(composer_row, padding={"left": "12", "right": "12", "top": "2", "bottom": "2"}),
			status_bar,
			spacing=0,
			expand=True,
		)

	# ── Composer helpers ────────────────────────────────────────────

	def on_composer_change(self, event=None) -> None:
		"""Track composer text from change events dispatched by the runtime."""
		if event is None:
			return
		if isinstance(event, dict):
			self._composer_value = str(event.get("value", event.get("data", "")))
		elif hasattr(event, "value") and event.value is not None:
			self._composer_value = str(event.value)
		elif hasattr(event, "data") and event.data is not None:
			self._composer_value = str(event.data)

	def get_composer_text(self) -> str:
		return self._composer_value.strip()

	def clear_composer(self) -> None:
		self._composer_value = ""

	# ── Header / status helpers ─────────────────────────────────────

	def set_title(self, title: str) -> None:
		if title.strip():
			self.title.patch(text=title)

	def set_status(self, status: str) -> None:
		self.status_text.patch(text=status)

	def set_context_info(self, text: str) -> None:
		self.context_info.patch(text=text)

	def use_genesis_context(self) -> bool:
		try:
			props = self.context_switch.to_dict().get("props", {})
			return bool(props.get("value", False))
		except Exception:
			return True

	# ── Message helpers ─────────────────────────────────────────────

	def _sync_thread(self, session=None) -> None:
		fixed_messages = []
		for msg in self._messages:
			align = msg.get("align", "left")
			if align == "start": align = "left"
			if align == "end": align = "right"
			fixed_messages.append({
				"text": msg.get("text", ""),
				"role": msg.get("role", "user"),
				"align": align,
				"name": "You" if msg.get("role") == "user" else "Genesis",
			})
		try:
			if session is not None:
				self.chat_thread.patch(session=session, messages=fixed_messages)
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
		self._messages.append(
			{
				"text": text,
				"role": "user",
				"align": "right",
			}
		)
		self._sync_thread(session)

	def add_assistant_message(self, text: str, session=None) -> None:
		self._messages.append(
			{
				"text": text,
				"role": "assistant",
				"align": "left",
			}
		)
		self._sync_thread(session)

	# ── Streaming ───────────────────────────────────────────────────

	def begin_streaming(self, message_id: str, session=None) -> None:
		if message_id in self._streaming_widgets:
			return
		self._messages.append(
			{
				"text": "",
				"role": "assistant",
				"align": "left",
			}
		)
		self._streaming_widgets[message_id] = len(self._messages) - 1
		self._streaming_text[message_id] = ""
		self._sync_thread(session)
		self.typing_indicator.patch(visible=True)
		self.set_status("Streaming response…")

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
