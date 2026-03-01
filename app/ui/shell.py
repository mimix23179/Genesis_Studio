from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from itertools import count
from pathlib import Path
from typing import Any

import butterflyui as ui

from app.config import AppPaths, RuntimeSettings, resolve_paths
from genesis.core.ws_server import GenesisRuntime
from .chat_page import ChatPage
from .sidebar_view import SidebarView
from .terminal_container import TerminalContainer


logger = logging.getLogger("genesis.shell")


# ━━━━━━━━━━━━━━━━━━━  Runtime Bridge  ━━━━━━━━━━━━━━━━━━━━━━━━━━━

class RuntimeBridge:
	"""Hosts / attaches to a Genesis runtime instance over WebSocket."""

	def __init__(self, on_message, settings: RuntimeSettings) -> None:
		self._on_message = on_message
		self._settings   = settings
		self._loop: asyncio.AbstractEventLoop | None = None
		self._ws   = None
		self._server = None
		self._runtime_port: int | None = None
		self._thread: threading.Thread | None = None
		self._connected = threading.Event()

	def start(self) -> None:
		self._thread = threading.Thread(target=self._run, daemon=True)
		self._thread.start()

	def _run(self) -> None:
		self._loop = asyncio.new_event_loop()
		asyncio.set_event_loop(self._loop)
		try:
			self._loop.run_until_complete(self._bootstrap())
		except Exception as exc:
			logger.exception("Runtime bridge crashed: %s", exc)

	async def _bootstrap(self) -> None:
		import websockets

		ports = [
			self._settings.preferred_port + offset
			for offset in range(self._settings.max_port_scan)
		]

		# Try connecting to an existing runtime first
		for port in ports:
			url = f"ws://{self._settings.host}:{port}"
			try:
				self._ws = await websockets.connect(url)
				self._runtime_port = port
				self._connected.set()
				await self._recv_loop()
				return
			except Exception:
				continue

		# No runtime found — start one ourselves
		for port in ports:
			try:
				runtime = GenesisRuntime(
					db_path=self._settings.db_path,
					host=self._settings.host,
					port=port,
				)
				self._server = await websockets.serve(
					runtime._ws_handler, self._settings.host, port,
				)
				self._ws = await websockets.connect(
					f"ws://{self._settings.host}:{port}"
				)
				self._runtime_port = port
				self._connected.set()
				await self._recv_loop()
				return
			except OSError:
				continue

		raise RuntimeError("Unable to connect or bind Genesis runtime on scanned ports")

	async def _recv_loop(self) -> None:
		if self._ws is None:
			return
		try:
			async for raw in self._ws:
				message = json.loads(raw)
				self._on_message(message)
		except Exception as exc:
			logger.warning("Runtime receive loop closed: %s", exc)

	def send(self, method: str, params: dict, msg_id: int | None = None) -> None:
		if self._loop is None or self._ws is None:
			return
		payload: dict[str, Any] = {
			"jsonrpc": "2.0",
			"method": method,
			"params": params,
		}
		if msg_id is not None:
			payload["id"] = msg_id
		encoded = json.dumps(payload, ensure_ascii=False)
		asyncio.run_coroutine_threadsafe(self._ws.send(encoded), self._loop)

	def wait_connected(self, timeout: float = 8.0) -> bool:
		return self._connected.wait(timeout)

	@property
	def runtime_port(self) -> int | None:
		return self._runtime_port


# ━━━━━━━━━━━━━━━━━━━  Shell  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class GenesisStudioShell:
	"""Top-level application controller — wires UI, bridge, and events."""

	# ── Colour tokens ──────────────────────────────────────────────
	_BG          = "#F8F9FB"
	_SURFACE     = "#FFFFFF"
	_BORDER      = "#C5C5C5"
	_TEXT         = "#1A1A2E"
	_MUTED        = "#6B7280"
	_ACCENT       = "#6366F1"
	_ACCENT_LIGHT = "#EEF2FF"

	def __init__(self, page: ui.Page, paths: AppPaths | None = None) -> None:
		self.page     = page
		self.paths    = paths or resolve_paths()
		self.settings = RuntimeSettings()

		self.chat_page = ChatPage()
		self.sidebar   = SidebarView(width=280)
		self.terminal  = TerminalContainer(self.paths)

		self.current_session_id: str | None = None
		self._sessions: list[dict[str, Any]] = []
		self._request_ids   = count(100)
		self._last_delta_refresh = 0.0
		self._terminal_visible   = False
		self._ui_loop: asyncio.AbstractEventLoop | None = None

		self.bridge = RuntimeBridge(
			on_message=self._on_runtime_message,
			settings=self.settings,
		)

	# ── Mount ───────────────────────────────────────────────────────

	def mount(self) -> None:
		try:
			self._ui_loop = asyncio.get_running_loop()
		except RuntimeError:
			self._ui_loop = None

		self.page.title = "Genesis Studio"

		# Register high-level callbacks on sidebar
		self.sidebar.on_new(self._on_new_chat)
		self.sidebar.on_select(self._open_session)
		self.sidebar.on_refresh(self._on_refresh_sessions)

		# Build the root widget tree
		self.page.root = self._build_root()

		# ── Explicit event binding (belt-and-suspenders) ──
		session = self.page.session

		# Composer: submit/send + text tracking
		self.chat_page.composer.on_submit(session, self._on_send)
		self.chat_page.composer.on_change(session, self.chat_page.on_composer_change)
		try:
			self.chat_page.composer.on_event(session, "send", self._on_send)
		except Exception:
			pass

		# Sidebar buttons
		self.sidebar.bind_events(session)

		# Terminal toggle icon
		self._terminal_toggle.on_click(session, self._toggle_terminal)

		# Terminal webview message bridge
		self.terminal.attach_event_handler(session, self._on_terminal_message)

		self._request_ui_refresh()

		# Background: start runtime bridge & post-connect init
		self.bridge.start()
		threading.Thread(target=self._post_connect_init, daemon=True).start()

	# ── Root layout ─────────────────────────────────────────────────

	def _build_root(self):
		# Terminal toggle in top toolbar
		self._terminal_toggle = ui.Button(
			text="Terminal",
			variant="outlined",
			events=["click"],
			style={
				"font_size": "12",
				"font_weight": "600",
				"border_radius": "8",
				"border_color": "self._TEXT",
				"color": "self._ACCENT",
				"padding_horizontal": "12",
				"padding_vertical": "4",
			},
		)

		toolbar = ui.Surface(
			ui.Row(
				ui.Spacer(),
				self._terminal_toggle,
				spacing=6,
			),
			padding={"left": "12", "right": "12", "top": "6", "bottom": "6"},
			bgcolor="#FFFFFF",
			border_color="rgba(0,0,0,0.06)",
			border_width="1",
		)

		chat_surface = ui.Column(
			toolbar,
			self.chat_page.build(),
			spacing="0",
			expand=True,
		)

		# Terminal area — starts hidden (height=0)
		self.terminal_view = self.terminal.build()
		self._terminal_slot = ui.Container(
			self.terminal_view, height="0",
			style={"overflow": "hidden"},
		)

		right = ui.Column(chat_surface, self._terminal_slot, spacing="0", expand=True)

		return ui.SplitPane(
			self.sidebar.build(),
			right,
			axis="horizontal",
			ratio="0.22",
			min_ratio="0.15",
			max_ratio="0.35",
			draggable=True,
			divider_size="1",
		)

	# ── Post-connect init ───────────────────────────────────────────

	def _post_connect_init(self) -> None:
		if not self.bridge.wait_connected(10.0):
			self.chat_page.set_status("Runtime unavailable")
			self._request_ui_refresh()
			return

		runtime_port = self.bridge.runtime_port
		self.chat_page.set_status(
			f"Connected · port {runtime_port}" if runtime_port else "Connected"
		)
		self.bridge.send("workspace.set", {"root": str(Path.cwd())}, msg_id=next(self._request_ids))
		self.bridge.send("session.list", {}, msg_id=next(self._request_ids))
		self.bridge.send("session.create", {"title": "New Conversation"}, msg_id=next(self._request_ids))

	# ── Terminal toggle ─────────────────────────────────────────────

	def _toggle_terminal(self, event=None) -> None:
		self._terminal_visible = not self._terminal_visible
		new_height = 300 if self._terminal_visible else 0
		self._terminal_slot.props["height"] = new_height
		try:
			self.page.session.update_props(self._terminal_slot.control_id, {"height": new_height})
		except Exception:
			pass
		if self._terminal_visible:
			self.terminal.open(self.page.session)
			self.terminal.send_output(self.page.session, "\r\nGenesis terminal opened\r\n")
		self._request_ui_refresh()

	# ── Terminal messages (from WebView JS) ─────────────────────────

	def _on_terminal_message(self, msg=None) -> None:
		if msg is None:
			return
		# msg may arrive as event object or raw dict
		payload = msg if isinstance(msg, dict) else getattr(msg, "data", msg)
		if isinstance(payload, str):
			try:
				payload = json.loads(payload)
			except Exception:
				payload = {"type": "raw", "data": payload}
		if not isinstance(payload, dict):
			return

		# Handle terminal close action from the terminal's close button
		if payload.get("type") == "control" and payload.get("action") == "close":
			self._terminal_visible = False
			self._terminal_slot.props["height"] = 0
			try:
				self.page.session.update_props(self._terminal_slot.control_id, {"height": 0})
			except Exception:
				pass
			self._request_ui_refresh()
			return

		# Forward as a runtime event
		self.bridge.send(
			"ui.event",
			{"type": f"terminal.{payload.get('type', 'unknown')}", "payload": payload},
			msg_id=None,
		)

		# Simple built-in command handling
		if payload.get("type") == "input":
			command = str(payload.get("data", "")).strip()
			if not command:
				return
			args = {"root": "."} if command == "ls" else {"root": command}
			self.bridge.send(
				"tool.call",
				{"tool": "fs.list", "args": args},
				msg_id=next(self._request_ids),
			)

	# ── Send message ────────────────────────────────────────────────

	def _on_send(self, event=None) -> None:
		# Try to extract text from the event payload first
		text = ""
		if event is not None:
			if isinstance(event, dict):
				text = str(event.get("value", event.get("data", ""))).strip()
			else:
				val = getattr(event, "value", None) or getattr(event, "data", None)
				if val:
					text = str(val).strip()
		if not text:
			text = self.chat_page.get_composer_text()
		if not text:
			return
		if not self.current_session_id:
			self.chat_page.set_status("No active session")
			self._request_ui_refresh()
			return

		self.chat_page.add_user_message(text)
		self.chat_page.clear_composer()
		self.chat_page.set_status("Waiting for response…")
		self._request_ui_refresh()

		outbound_text = text
		if self.chat_page.use_genesis_context():
			context_blob, stats = self._build_genesis_context()
			self.chat_page.set_context_info(
				f"Context: {stats['files']} files · {stats['chars']} chars"
			)
			if context_blob:
				outbound_text = (
					"You are Genesis running locally. Use the following source context "
					"for accuracy.\n\n"
					"[Genesis Source Context Start]\n"
					f"{context_blob}\n"
					"[Genesis Source Context End]\n\n"
					"User request:\n"
					f"{text}"
				)
		else:
			self.chat_page.set_context_info("Context: disabled")

		self.bridge.send(
			"chat.send",
			{
				"session_id": self.current_session_id,
				"message": {"role": "user", "content": [{"type": "text", "text": outbound_text}]},
			},
			msg_id=next(self._request_ids),
		)

	# ── Sidebar callbacks ───────────────────────────────────────────

	def _on_new_chat(self, event=None) -> None:
		self.bridge.send(
			"session.create", {"title": "New Conversation"},
			msg_id=next(self._request_ids),
		)

	def _on_refresh_sessions(self, event=None) -> None:
		self.bridge.send("session.list", {}, msg_id=next(self._request_ids))

	def _open_session(self, session_id: str) -> None:
		self.current_session_id = session_id
		self.sidebar.set_active(session_id)
		self.bridge.send(
			"session.open", {"session_id": session_id},
			msg_id=next(self._request_ids),
		)
		self._request_ui_refresh()

	# ── Runtime message dispatcher ──────────────────────────────────

	def _on_runtime_message(self, message: dict) -> None:
		# JSON-RPC response (success)
		if "id" in message and "result" in message:
			self._handle_response(message["result"])
			return

		# JSON-RPC response (error)
		if "id" in message and "error" in message:
			err = message.get("error", {})
			msg = err.get("message") if isinstance(err, dict) else str(err)
			self.chat_page.set_status(f"Runtime error: {msg}")
			self._request_ui_refresh()
			return

		method = message.get("method")
		params = message.get("params", {})

		if method == "session.updated":
			self.bridge.send("session.list", {}, msg_id=next(self._request_ids))
			return

		if method == "chat.begin":
			message_id = params.get("message_id")
			if message_id:
				self.chat_page.begin_streaming(message_id)
				self._request_ui_refresh()
			return

		if method == "chat.delta":
			message_id = params.get("message_id")
			if not message_id:
				return
			self.chat_page.add_delta(message_id, params.get("delta", ""))
			now = time.monotonic()
			if now - self._last_delta_refresh >= 0.05:
				self._last_delta_refresh = now
				self._request_ui_refresh()
			return

		if method == "chat.message":
			msg = params.get("message", {})
			content = msg.get("content", [])
			text = ""
			if isinstance(content, list):
				text = "".join(
					part.get("text", "") for part in content if isinstance(part, dict)
				)
			self.chat_page.finalize_stream(msg.get("id", ""), text)
			self._request_ui_refresh()
			return

		if method == "tool.result" and self._terminal_visible:
			ok = bool(params.get("ok", False))
			result = params.get("result", {}) if isinstance(params, dict) else {}
			if ok and isinstance(result, dict) and isinstance(result.get("items"), list):
				lines = []
				for item in result["items"]:
					name = item.get("name", "")
					suffix = "/" if item.get("is_dir") else ""
					lines.append(f"{name}{suffix}")
				rendered = "\r\n".join(lines) + "\r\n"
			else:
				rendered = json.dumps(params, ensure_ascii=False, indent=2) + "\r\n"
			self.terminal.send_output(self.page.session, rendered)

		if method == "log.append":
			line = params.get("line")
			if isinstance(line, str) and line.strip():
				self.chat_page.set_status(line)
				self._request_ui_refresh()

	def _handle_response(self, result: dict) -> None:
		if "sessions" in result:
			self._sessions = result.get("sessions", [])
			if not self.current_session_id and self._sessions:
				self.current_session_id = self._sessions[0].get("id")
			self.sidebar.set_sessions(self._sessions, self.current_session_id)
			self._request_ui_refresh()
			return

		if "session_id" in result and "title" in result and "messages" not in result:
			self.current_session_id = result.get("session_id")
			self.sidebar.set_active(self.current_session_id)
			self.chat_page.set_title(result.get("title", "Genesis"))
			self.chat_page.clear_messages()
			self.bridge.send(
				"session.open",
				{"session_id": self.current_session_id},
				msg_id=next(self._request_ids),
			)
			self._request_ui_refresh()
			return

		if "messages" in result:
			self.chat_page.clear_messages()
			self.chat_page.set_title(result.get("title", "Genesis"))
			for item in result.get("messages", []):
				role = item.get("role", "assistant")
				content = item.get("content", [])
				text = ""
				if isinstance(content, list):
					text = "".join(
						part.get("text", "") for part in content if isinstance(part, dict)
					)
				if role == "user":
					self.chat_page.add_user_message(text)
				elif role == "assistant":
					self.chat_page.add_assistant_message(text)
			self._request_ui_refresh()

	# ── UI refresh helper ───────────────────────────────────────────

	def _request_ui_refresh(self) -> None:
		if self._ui_loop is None:
			try:
				self.page.update()
			except Exception:
				pass
			return
		try:
			self._ui_loop.call_soon_threadsafe(self.page.update)
		except Exception:
			try:
				self.page.update()
			except Exception:
				pass

	# ── Genesis source-context builder ──────────────────────────────

	def _build_genesis_context(
		self, max_files: int = 12, max_chars: int = 24000,
	) -> tuple[str, dict[str, int]]:
		genesis_root = self.paths.root / "genesis"
		if not genesis_root.exists():
			return "", {"files": 0, "chars": 0}

		selected_parts: list[str] = []
		total_chars = 0
		used_files  = 0

		candidates = sorted(genesis_root.rglob("*.py"))
		for file_path in candidates:
			if used_files >= max_files or total_chars >= max_chars:
				break
			try:
				text = file_path.read_text(encoding="utf-8", errors="replace")
			except Exception:
				continue

			remaining = max_chars - total_chars
			if remaining <= 0:
				break

			snippet = text[:remaining]
			rel = file_path.relative_to(self.paths.root).as_posix()
			block = f"# FILE: {rel}\n{snippet}\n"
			selected_parts.append(block)
			total_chars += len(block)
			used_files += 1

		return "\n".join(selected_parts), {"files": used_files, "chars": total_chars}
