from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import websockets
from itertools import count
from pathlib import Path
from typing import Any

import butterflyui as ui

from app.config import AppPaths, RuntimeSettings, resolve_paths
from app.utils import read_json_file
from genesis.core.ws_server import GenesisRuntime
from .chat_page import ChatPage
from .sidebar_view import SidebarView
from .terminal_container import TerminalContainer
from .terminal_process import TerminalProcess


logger = logging.getLogger("genesis.shell")


# ━━━━━━━━━━━━━━━━━━━  Runtime Bridge  ━━━━━━━━━━━━━━━━━━━━━━━━━━━

class RuntimeBridge:
	"""Hosts / attaches to a Genesis runtime instance over WebSocket."""

	def __init__(self, on_message, on_message_loop, settings: RuntimeSettings) -> None:
		self._on_message = on_message
		self._on_message_loop = on_message_loop
		self._settings   = settings
		self._loop: asyncio.AbstractEventLoop | None = None
		self._ws   = None
		self._server = None
		self._runtime: GenesisRuntime | None = None
		self._runtime_port: int | None = None
		self._thread: threading.Thread | None = None
		self._connected = threading.Event()
		self._pending_messages: list[dict] = []

	def start(self) -> None:
		self._thread = threading.Thread(target=self._run, daemon=True)
		self._thread.start()

	def _run(self) -> None:
		self._loop = asyncio.new_event_loop()
		asyncio.set_event_loop(self._loop)
		try:
			self._loop.run_until_complete(self._bootstrap())
		except Exception:
			pass

	async def _bootstrap(self) -> None:

		ports = [
			self._settings.preferred_port + offset
			for offset in range(self._settings.max_port_scan)
		]

		for port in ports:
			endpoint = f"{self._settings.host}:{port}"

			try:
				self._ws = await websockets.connect(
					f"ws://{self._settings.host}:{port}",
					open_timeout=0.75,
				)
				self._runtime_port = port
				self._connected.set()
				await self._recv_loop()
				return
			except Exception:
				pass

			try:
				self._runtime = GenesisRuntime(
					db_path=self._settings.db_path,
					host=self._settings.host,
					port=port,
				)
				self._server = await websockets.serve(
					self._runtime._ws_handler,
					self._settings.host,
					port,
				)
				self._ws = await websockets.connect(
					f"ws://{self._settings.host}:{port}",
					open_timeout=1.5,
				)
				self._runtime_port = port
				self._connected.set()
				await self._recv_loop()
				return
			except Exception as start_exc:
				self._runtime = None
				continue

		raise RuntimeError("Unable to connect or bind Genesis runtime on scanned ports")

	async def _recv_loop(self) -> None:
		if self._ws is None:
			return
		try:
			async for raw in self._ws:
				message = json.loads(raw)
				try:
					# Schedule the message handler on the UI loop to avoid race conditions
					if self._on_message_loop is not None:
						self._on_message_loop.call_soon_threadsafe(self._on_message, message)
					else:
						# Buffer messages until UI loop is ready
						self._pending_messages.append(message)
				except Exception: 
					pass
		except Exception:
			pass

	def flush_pending_messages(self) -> None:
		"""Flush any buffered messages to the UI loop. Called after mount()."""
		if self._on_message_loop is not None and self._pending_messages:
			for message in self._pending_messages:
				try:
					self._on_message_loop.call_soon_threadsafe(self._on_message, message)
				except Exception:
					pass
			self._pending_messages.clear()

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
		self._request_meta: dict[int, dict[str, Any]] = {}
		self._session_view_cache: dict[str, dict[str, Any]] = {}
		self._last_delta_refresh = 0.0
		self._terminal_visible   = False
		self._ui_loop: asyncio.AbstractEventLoop | None = None
		self._terminal_process: TerminalProcess | None = None
		self._preferred_shell = self._resolve_preferred_shell()

		self.bridge = RuntimeBridge(
			on_message=self._on_runtime_message,
			on_message_loop=self._ui_loop,
			settings=self.settings,
		)

	# ── Mount ───────────────────────────────────────────────────────

	def mount(self) -> None:
		try:
			self._ui_loop = asyncio.get_running_loop()
		except RuntimeError:
			self._ui_loop = None

		# Update the bridge with the UI loop now that we have it
		self.bridge._on_message_loop = self._ui_loop
		# Flush any messages that arrived before mount()
		self.bridge.flush_pending_messages()

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
		# Only request session list - don't auto-create a session
		# Let _handle_response decide if we need a new session
		self._send_runtime("session.list", {}, intent="session.list")
		self._send_runtime("workspace.set", {"root": str(Path.cwd())}, intent="workspace.set")

	# ── Terminal toggle ─────────────────────────────────────────────

	def _toggle_terminal(self, event=None) -> None:
		self._terminal_visible = not self._terminal_visible
		new_height = 420 if self._terminal_visible else 0
		self._terminal_slot.props["height"] = new_height
		try:
			self.page.session.update_props(self._terminal_slot.control_id, {"height": new_height})
		except Exception:
			pass
		if self._terminal_visible:
			self._ensure_terminal_process()
			self.terminal.open(self.page.session)
			workspace_name = self.paths.root.name
			shell_name = self._preferred_shell or "auto"
			self._emit_terminal_output(
				f"\r\n[{workspace_name}>] shell={shell_name} cwd={self.paths.root}\r\n"
			)
		else:
			self._stop_terminal_process()
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
			self._stop_terminal_process()
			try:
				self.page.session.update_props(self._terminal_slot.control_id, {"height": 0})
			except Exception:
				pass
			self._request_ui_refresh()
			return

		if payload.get("type") == "input":
			self._ensure_terminal_process()
			command = str(payload.get("data", "")).strip()
			if not command:
				return
			if self._terminal_process is None:
				self._emit_terminal_output("\r\nUnable to start shell process.\r\n")
				return
			self._terminal_process.write_line(command)

	# ── Send message ────────────────────────────────────────────────

	def _on_send(self, event=None) -> None:
		# Try to extract text from the event payload first
		text = ""
		if event is not None:
			if isinstance(event, dict):
				# Check payload.value first (MessageComposer structure)
				payload = event.get("payload", {})
				if isinstance(payload, dict):
					text = str(payload.get("value", "")).strip()
				# Fallback to direct keys
				if not text:
					text = str(
						event.get("value")
						or event.get("text")
						or event.get("data")
						or event.get("message")
						or ""
					).strip()
			else:
				val = (
					getattr(event, "value", None)
					or getattr(event, "text", None)
					or getattr(event, "data", None)
				)
				if val:
					text = str(val).strip()
		# If no text found, fallback to composer value (covers some edge cases)
		if not text:
			text = self.chat_page.get_composer_text()
		if not text:
			return
		# Always show the user's message locally right away so the UI feels
		# responsive even when the runtime session hasn't been established yet.
		self.chat_page.add_user_message(text, self.page.session)

		self.chat_page.clear_composer()
		# If there's no active runtime session, show the message locally and
		# avoid attempting to send to the runtime. This prevents drops and
		# keeps the conversation visible immediately.
		if not self.current_session_id:
			self.chat_page.set_status("No active session")
			self._request_ui_refresh()
			return

		# With an active session, proceed to send and show waiting state.
		self.chat_page.set_status("Waiting for response…")
		self._request_ui_refresh()

		outbound_text = text
		system_prompt: str | None = None
		if self.chat_page.use_genesis_context():
			context_blob, stats = self._build_genesis_context()
			self.chat_page.set_context_info(
				f"Context: {stats['files']} files · {stats['chars']} chars"
			)
			if context_blob:
				system_prompt = (
					"You are Genesis running locally. Use the following source context "
					"for accuracy.\n\n"
					"[Genesis Source Context Start]\n"
					f"{context_blob}\n"
					"[Genesis Source Context End]\n\n"
				)
		else:
			self.chat_page.set_context_info("Context: disabled")

		self._send_runtime(
			"chat.send",
			{
				"session_id": self.current_session_id,
				"message": {"role": "user", "content": [{"type": "text", "text": outbound_text}]},
				"system_prompt": system_prompt,
			},
			intent="chat.send",
		)
		self._cache_active_session_state()

	# ── Sidebar callbacks ───────────────────────────────────────────

	def _on_new_chat(self, event=None) -> None:
		"""Create a new conversation - update UI immediately while waiting for runtime."""
		
		# Optimistically update UI to show we're creating a new session
		self.chat_page.set_status("Creating new conversation...")
		self._request_ui_refresh()
		
		# Send request to runtime
		self._cache_active_session_state()
		self._send_runtime("session.create", {"title": "New Conversation"}, intent="session.create")

	def _on_refresh_sessions(self, event=None) -> None:
		"""Refresh the conversations list from the runtime."""
		logger.info("[GenesisUI] Refreshing sessions...")
		self.chat_page.set_status("Refreshing conversations...")
		self._request_ui_refresh()
		self._send_runtime("session.list", {}, intent="session.list")

	def _open_session(self, session_id: str) -> None:
		"""Switch to a different conversation."""
		logger.info(f"[GenesisUI] Opening session: {session_id}")
		if self.current_session_id == session_id:
			return

		self._cache_active_session_state()
		self.current_session_id = session_id
		self.sidebar.set_active(session_id)
		cached = self._session_view_cache.get(session_id)
		if cached:
			self.chat_page.set_title(str(cached.get("title", "Genesis")))
			self.chat_page.restore_messages_snapshot(cached.get("messages", []), self.page.session)
			self.chat_page.set_status("Loaded conversation")
		else:
			self.chat_page.clear_messages(self.page.session)
		self.chat_page.set_status("Loading conversation...")
		self._request_ui_refresh()

		self._send_runtime(
			"session.open",
			{"session_id": session_id},
			intent="session.open",
			meta={"session_id": session_id},
		)

	# ── Runtime message dispatcher ──────────────────────────────────

	def _on_runtime_message(self, message: dict) -> None:
		# JSON-RPC response (success)
		if "id" in message and "result" in message:
			self._handle_response(message.get("id"), message["result"])
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
			self._send_runtime("session.list", {}, intent="session.list")
			return

		if method == "chat.begin":
			message_id = params.get("message_id")
			if message_id:
				self.chat_page.begin_streaming(message_id, self.page.session)
				self._request_ui_refresh()
			return

		if method == "chat.delta":
			message_id = params.get("message_id")
			if not message_id:
				return
			self.chat_page.add_delta(message_id, params.get("delta", ""), self.page.session)
			now = time.monotonic()
			if now - self._last_delta_refresh >= 0.05:
				self._last_delta_refresh = now
				self._cache_active_session_state()
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
			self.chat_page.finalize_stream(msg.get("id", ""), text, self.page.session)
			self._cache_active_session_state()
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
			self._emit_terminal_output(rendered)

		if method == "log.append":
			line = params.get("line")
			if isinstance(line, str) and line.strip():
				self.chat_page.set_status(line)
				self._request_ui_refresh()

	def _handle_response(self, request_id: int | None, result: dict) -> None:
		request_meta = self._request_meta.pop(request_id, {}) if isinstance(request_id, int) else {}
		request_intent = str(request_meta.get("intent", ""))
		requested_session_id = str(request_meta.get("session_id", "")).strip()

		if "sessions" in result:
			logger.info(f"[GenesisUI] Received sessions list: {result.get('sessions', [])}")
			self._sessions = result.get("sessions", [])
			if not self.current_session_id and self._sessions:
				self.current_session_id = self._sessions[0].get("id")
			self.sidebar.set_sessions(self._sessions, self.current_session_id)
			self._request_ui_refresh()
			# If no sessions exist, create one automatically
			if not self._sessions:
				logger.info("[GenesisUI] No sessions found, creating initial session...")
				self._on_new_chat()
			elif self.current_session_id and request_intent == "session.list":
				self._send_runtime(
					"session.open",
					{"session_id": self.current_session_id},
					intent="session.open",
					meta={"session_id": self.current_session_id},
				)
			return

		if "session_id" in result and "title" in result and "messages" not in result:
			# This is a session.create response - update local state immediately
			session_id = result.get("session_id")
			title = result.get("title", "New Conversation")
			logger.info(f"[GenesisUI] Session created: {session_id}")
			
			# Add to local sessions list optimistically
			new_session = {"id": session_id, "title": title}
			if not any(s.get("id") == session_id for s in self._sessions):
				self._sessions.insert(0, new_session)
			
			self.current_session_id = session_id
			self.sidebar.set_sessions(self._sessions, session_id)
			self.chat_page.set_title(title)
			self.chat_page.clear_messages(self.page.session)
			self._session_view_cache[session_id] = {
				"title": title,
				"messages": [],
			}
			
			# Now open the session to get its messages (if any)
			self._send_runtime(
				"session.open",
				{"session_id": session_id},
				intent="session.open",
				meta={"session_id": session_id},
			)
			self._request_ui_refresh()
			return

		if "messages" in result:
			if requested_session_id and self.current_session_id and requested_session_id != self.current_session_id:
				logger.info(
					"[GenesisUI] Ignoring stale session.open response for %s (active=%s)",
					requested_session_id,
					self.current_session_id,
				)
				return

			opened_session_id = str(result.get("session_id", self.current_session_id or "")).strip()
			if opened_session_id and self.current_session_id and opened_session_id != self.current_session_id:
				return

			# This is a session.open response
			self.chat_page.clear_messages(self.page.session)
			title = result.get("title", "Genesis")
			self.chat_page.set_title(title)
			for item in result.get("messages", []):
				role = item.get("role", "assistant")
				content = item.get("content", [])
				text = ""
				if isinstance(content, list):
					text = "".join(
						part.get("text", "") for part in content if isinstance(part, dict)
					)
				if role == "user":
					self.chat_page.add_user_message(self._sanitize_user_display_text(text), self.page.session)
				elif role == "assistant":
					self.chat_page.add_assistant_message(text, self.page.session)
			if opened_session_id:
				self._session_view_cache[opened_session_id] = {
					"title": title,
					"messages": self.chat_page.get_messages_snapshot(),
				}
			self.chat_page.set_status("Idle")
			self._request_ui_refresh()

	def _send_runtime(self, method: str, params: dict, *, intent: str, meta: dict[str, Any] | None = None) -> None:
		request_id = next(self._request_ids)
		request_meta = {"intent": intent}
		if isinstance(meta, dict):
			request_meta.update(meta)
		self._request_meta[request_id] = request_meta
		self.bridge.send(method, params, msg_id=request_id)

	def _cache_active_session_state(self) -> None:
		if not self.current_session_id:
			return
		title = getattr(self.chat_page.title, "props", {}).get("text", "Genesis")
		self._session_view_cache[self.current_session_id] = {
			"title": str(title),
			"messages": self.chat_page.get_messages_snapshot(),
		}

	def _sanitize_user_display_text(self, text: str) -> str:
		if not text:
			return ""
		if "[Genesis Source Context Start]" not in text:
			return text
		marker = "User request:\n"
		if marker in text:
			return text.split(marker, 1)[1].strip()
		return text

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

	def _resolve_preferred_shell(self) -> str:
		payload = read_json_file(self.paths.terminal_payload, default={})
		if isinstance(payload, dict):
			value = payload.get("preferred_shell") or payload.get("shell")
			if isinstance(value, str) and value.strip():
				return value.strip()
		env_value = os.environ.get("GENESIS_SHELL")
		if env_value and env_value.strip():
			return env_value.strip()
		return ""

	def _ensure_terminal_process(self) -> None:
		if self._terminal_process is not None and self._terminal_process.is_running():
			return
		process = TerminalProcess(
			workspace_root=self.paths.root,
			on_output=self._emit_terminal_output,
			on_closed=self._on_terminal_process_closed,
			preferred_shell=self._preferred_shell or None,
		)
		if process.start():
			self._terminal_process = process
		else:
			self._terminal_process = None

	def _stop_terminal_process(self) -> None:
		process = self._terminal_process
		self._terminal_process = None
		if process is not None:
			process.stop()

	def _emit_terminal_output(self, text: str) -> None:
		if not text:
			return
		if self._ui_loop is None:
			self.terminal.send_output(self.page.session, text)
			return

		try:
			loop = asyncio.get_running_loop()
		except RuntimeError:
			loop = None

		if loop is self._ui_loop:
			self.terminal.send_output(self.page.session, text)
			return

		try:
			self._ui_loop.call_soon_threadsafe(self.terminal.send_output, self.page.session, text)
		except Exception:
			self.terminal.send_output(self.page.session, text)

	def _on_terminal_process_closed(self, exit_code: int | None) -> None:
		self._terminal_process = None
		self._emit_terminal_output(f"\r\nShell process closed ({exit_code}).\r\n")

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
