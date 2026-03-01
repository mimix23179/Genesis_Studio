from __future__ import annotations

import json
from typing import Optional

import butterflyui as ui

from app.config import AppPaths
from app.utils import json_for_script_tag, read_json_file, read_text_file


class TerminalContainer:
	"""Wraps xterm.js inside a ButterflyUI WebView for reliable JS execution."""

	def __init__(self, paths: AppPaths) -> None:
		self.paths = paths
		self.view: Optional[ui.WebView] = None

	def build(self) -> ui.WebView:
		template = read_text_file(self.paths.templates_root / "terminal.html")
		css = read_text_file(self.paths.static_root / "css" / "terminal.css")
		js = read_text_file(self.paths.static_root / "js" / "terminal.js")

		payload = read_json_file(
			self.paths.terminal_payload,
			default={"welcome": "Genesis Shell ready"},
		)

		html = template.replace("__COMPONENT_CSS__", css)
		html = html.replace("__COMPONENT_JS__", js)
		html = html.replace(
			"</body>",
			f"<script>window.__TERMINAL_PAYLOAD__ = {json_for_script_tag(payload)};</script></body>",
		)

		self.view = ui.WebView(
			html=html,
			javascript_enabled=True,
			dom_storage_enabled=True,
			allow_file_access=True,
			events=["message"],
			style={"min_height": 0},
		)
		return self.view

	def attach_event_handler(self, session, callback) -> None:
		"""Bind the 'message' event so callHandler('message', …) from JS reaches Python."""
		if self.view is None:
			return
		self.view.on_event(session, "message", callback)

	def open(self, session) -> None:
		"""Focus the terminal input after it becomes visible."""
		self._run_js(session, "document.getElementById('command_input')?.focus();")

	def close(self, session) -> None:
		"""No-op; container height hides the widget."""
		pass

	def send_output(self, session, text: str) -> None:
		"""Write text into the running xterm instance."""
		escaped = json.dumps(text, ensure_ascii=False)
		self._run_js(session, f"window.__genesis_receive({{type:'output',data:{escaped}}});")

	def _run_js(self, session, script: str) -> None:
		if self.view is None:
			return
		try:
			self.view.run_javascript(session, script)
		except Exception:
			pass
