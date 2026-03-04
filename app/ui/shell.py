from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from itertools import count
from pathlib import Path
from typing import Any

import butterflyui as ui
import websockets

from app.config import AppPaths, RuntimeSettings, load_runtime_settings, resolve_paths
from genesis.backend import OllamaRuntime
from .chat_page import ChatPage
from .settings_page import SettingsPage
from .sidebar_view import SidebarView
from .terminal_container import TerminalContainer
from .terminal_process import TerminalProcess

logger = logging.getLogger("genesis.shell")


class RuntimeBridge:
    """Hosts or attaches to runtime over WebSocket JSON-RPC."""

    def __init__(
        self,
        *,
        on_message,
        on_message_loop,
        settings: RuntimeSettings,
    ) -> None:
        self._on_message = on_message
        self._on_message_loop = on_message_loop
        self._settings = settings

        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws = None
        self._server = None
        self._runtime: OllamaRuntime | None = None
        self._runtime_port: int | None = None
        self._thread: threading.Thread | None = None
        self._connected = threading.Event()
        self._pending_messages: list[dict[str, Any]] = []

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._bootstrap())
        except Exception:
            logger.exception("Runtime bridge bootstrap failed")

    async def _bootstrap(self) -> None:
        ports = [
            self._settings.preferred_port + offset
            for offset in range(self._settings.max_port_scan)
        ]

        for port in ports:
            endpoint = f"ws://{self._settings.host}:{port}"

            # Try attach first.
            try:
                self._ws = await websockets.connect(endpoint, open_timeout=0.75)
                self._runtime_port = port
                self._connected.set()
                await self._recv_loop()
                return
            except Exception:
                self._ws = None

            # Try local host runtime.
            try:
                self._runtime = OllamaRuntime(
                    model=self._settings.model,
                    ollama_base_url=self._settings.ollama_base_url,
                    request_timeout=self._settings.request_timeout,
                )
                self._server = await self._runtime.start(self._settings.host, port)
                await asyncio.sleep(0.12)
                self._ws = await websockets.connect(endpoint, open_timeout=1.5)
                self._runtime_port = port
                self._connected.set()
                await self._recv_loop()
                return
            except Exception:
                self._ws = None
                self._server = None
                self._runtime = None

        raise RuntimeError("Unable to connect or bind Genesis runtime on scanned ports")

    async def _recv_loop(self) -> None:
        if self._ws is None:
            return
        try:
            async for raw in self._ws:
                message = json.loads(raw)
                try:
                    if self._on_message_loop is not None:
                        self._on_message_loop.call_soon_threadsafe(self._on_message, message)
                    else:
                        self._pending_messages.append(message)
                except Exception:
                    logger.exception("Failed to dispatch runtime message to UI loop")
        except Exception:
            logger.exception("Runtime websocket receive loop stopped")

    def flush_pending_messages(self) -> None:
        if self._on_message_loop is None or not self._pending_messages:
            return
        for message in self._pending_messages:
            try:
                self._on_message_loop.call_soon_threadsafe(self._on_message, message)
            except Exception:
                logger.exception("Failed to flush pending runtime message")
        self._pending_messages.clear()

    def send(self, method: str, params: dict[str, Any], msg_id: int | None = None) -> None:
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


class GenesisStudioShell:
    """Top-level app controller wiring UI, runtime, and terminal."""

    _BG = "#F8F9FB"
    _SURFACE = "#FFFFFF"
    _BORDER = "#C5C5C5"
    _TEXT = "#1A1A2E"

    def __init__(self, page: ui.Page, paths: AppPaths | None = None) -> None:
        self.page = page
        self.paths = paths or resolve_paths()
        self.settings = load_runtime_settings(self.paths.settings_file)

        self.chat_page = ChatPage()
        self.settings_page = SettingsPage(self.paths.settings_file)
        self.sidebar = SidebarView(width=280)
        self.terminal = TerminalContainer(self.paths)

        self.current_session_id: str | None = None
        self._sessions: list[dict[str, Any]] = []
        self._request_ids = count(100)
        self._request_meta: dict[int, dict[str, Any]] = {}
        self._session_view_cache: dict[str, dict[str, Any]] = {}
        self._last_delta_refresh = 0.0
        self._terminal_visible = False
        self._ui_loop: asyncio.AbstractEventLoop | None = None
        self._terminal_process: TerminalProcess | None = None
        self._preferred_shell = self._resolve_preferred_shell()
        self._active_view = "chat"

        self.bridge = RuntimeBridge(
            on_message=self._on_runtime_message,
            on_message_loop=self._ui_loop,
            settings=self.settings,
        )

    def mount(self) -> None:
        try:
            self._ui_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._ui_loop = None

        self.bridge._on_message_loop = self._ui_loop
        self.bridge.flush_pending_messages()

        self.page.title = "Genesis Studio"
        self.page.set_style_pack("base")
        self.page.bgcolor = "#F7F7F8"

        self.sidebar.on_new(self._on_new_chat)
        self.sidebar.on_select(self._open_session)
        self.sidebar.on_refresh(self._on_refresh_sessions)

        self.page.root = self._build_root()

        session = self.page.session
        self.chat_page.composer.on_submit(session, self._on_send)
        self.chat_page.composer.on_change(session, self.chat_page.on_composer_change)
        self.chat_page.send_button.on_click(session, self._on_send)
        self.settings_page.bind_events(
            session,
            self._on_theme_change,
            on_runtime_save=self._on_runtime_save,
            on_runtime_health=self._on_runtime_health_request,
            on_runtime_shell_change=self._on_terminal_shell_change,
        )
        self.sidebar.bind_events(session)

        self._terminal_toggle.on_click(session, self._toggle_terminal)
        self._settings_toggle.on_click(session, self._toggle_settings)
        self.terminal.bind_events(
            session,
            on_command=self._on_terminal_command,
            on_shell_change=self._on_terminal_shell_change,
            on_clear=self._on_terminal_clear,
            on_restart=self._on_terminal_restart,
            on_key_event=self._on_terminal_key_event,
        )
        self.terminal.set_shell(self._preferred_shell)

        self._request_ui_refresh()

        self.bridge.start()
        threading.Thread(target=self._post_connect_init, daemon=True).start()

    def _build_root(self):
        self._settings_toggle = ui.Button(
            text="Settings",
            variant="outlined",
            events=["click"],
            font_size=12,
            font_weight="600",
            radius=8,
            border_color=self._BORDER,
            border_width=1,
            text_color=self._TEXT,
            bgcolor="#FFFFFF",
            content_padding={"left": 12, "right": 12, "top": 4, "bottom": 4},
        )
        self._terminal_toggle = ui.Button(
            text="Terminal",
            variant="outlined",
            events=["click"],
            font_size=12,
            font_weight="600",
            radius=8,
            border_color=self._BORDER,
            border_width=1,
            text_color=self._TEXT,
            bgcolor="#FFFFFF",
            content_padding={"left": 12, "right": 12, "top": 4, "bottom": 4},
        )

        toolbar = ui.Surface(
            ui.Row(self._settings_toggle, self._terminal_toggle, ui.Spacer(), spacing=6),
            padding={"left": "12", "right": "12", "top": "6", "bottom": "6"},
            bgcolor="#FFFFFF",
            border_color=self._BORDER,
            border_width="1",
        )

        self.chat_view = ui.Container(self.chat_page.build(), expand=True, visible=True)
        self.settings_view = ui.Container(self.settings_page.build(), expand=True, visible=False)

        chat_surface = ui.Column(toolbar, self.chat_view, self.settings_view, spacing="0", expand=True)
        self.terminal_view = self.terminal.build()
        self._terminal_slot = ui.Container(self.terminal_view, height="0", style={"overflow": "hidden"})

        right = ui.Column(chat_surface, self._terminal_slot, spacing="0", expand=True)
        return ui.Row(self.sidebar.build(), right, expand=True, spacing=0)

    def _post_connect_init(self) -> None:
        if not self.bridge.wait_connected(10.0):
            self.chat_page.set_status("Runtime unavailable")
            self.settings_page.set_runtime_status("Runtime unavailable")
            self._request_ui_refresh()
            return

        runtime_port = self.bridge.runtime_port
        status = f"Connected - port {runtime_port}" if runtime_port else "Connected"
        self.chat_page.set_status(status)
        self.settings_page.set_runtime_status(status)

        self._send_runtime("session.list", {}, intent="session.list")
        self._send_runtime("workspace.set", {"root": str(Path.cwd())}, intent="workspace.set")
        self._send_runtime("runtime.info", {}, intent="runtime.info")
        self._send_runtime("runtime.health", {}, intent="runtime.health")

    def _toggle_settings(self, event=None) -> None:
        _ = event
        self._active_view = "settings" if self._active_view == "chat" else "chat"
        show_settings = self._active_view == "settings"
        self.chat_view.patch(visible=not show_settings)
        self.settings_view.patch(visible=show_settings)
        self._settings_toggle.patch(text="Back" if show_settings else "Settings")
        self._request_ui_refresh()

    def _on_theme_change(self, value=None, event=None) -> None:
        _ = event
        selected = str(value or "").strip()
        if not selected:
            selected = self.settings_page.theme_select.to_dict().get("props", {}).get("value", "light")
        theme = self.settings_page.apply_theme_change(str(selected))
        self.page.bgcolor = "#0F1115" if theme == "dark" else "#F7F7F8"
        self._request_ui_refresh()

    def _on_runtime_save(self, event=None) -> None:
        _ = event
        config = self.settings_page.get_runtime_config(session=self.page.session)
        saved = self.settings_page.apply_runtime_change(config)
        self.settings = load_runtime_settings(self.paths.settings_file)
        self.bridge._settings = self.settings
        self._preferred_shell = str(saved.get("preferred_shell", "auto")).strip() or "auto"
        self.terminal.set_shell(self._preferred_shell)
        self.settings_page.set_runtime_status("Runtime settings saved. Reconnect app/runtime to apply model/base URL.")
        self._request_ui_refresh()

    def _on_runtime_health_request(self, event=None) -> None:
        _ = event
        self.settings_page.set_runtime_status("Requesting runtime health...")
        self._send_runtime("runtime.health", {}, intent="runtime.health")
        self._request_ui_refresh()

    def _toggle_terminal(self, event=None) -> None:
        _ = event
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
            shell_name = (
                self._terminal_process.active_shell
                if self._terminal_process is not None
                else (self._preferred_shell or "auto")
            )
            self.terminal.set_status(f"{workspace_name} - shell {shell_name}")
            self._emit_terminal_output(
                f"\r\n[{workspace_name}>] shell={shell_name} cwd={self.paths.root}\r\n"
            )
        else:
            self._stop_terminal_process()
            self.terminal.set_status("Stopped")
        self._request_ui_refresh()

    def _on_terminal_command(self, command: str) -> None:
        self._ensure_terminal_process()
        text = str(command or "").strip()
        if not text:
            return
        if self._terminal_process is None:
            self._emit_terminal_output("\r\nUnable to start shell process.\r\n")
            return
        self._terminal_process.write_line(text)

    def _on_terminal_key_event(self, event: Any = None) -> None:
        if not self._terminal_visible:
            return
        self._ensure_terminal_process()
        if self._terminal_process is None:
            return
        self._terminal_process.send_key_event(event)

    def _on_terminal_shell_change(self, value=None, event=None) -> None:
        _ = event
        selected = str(value or "").strip() or "auto"
        self._preferred_shell = selected
        self.terminal.set_shell(selected)
        runtime = self.settings_page.get_runtime_config(session=self.page.session)
        runtime["preferred_shell"] = selected
        self.settings_page.apply_runtime_change(runtime)
        self.settings = load_runtime_settings(self.paths.settings_file)
        self.bridge._settings = self.settings
        self.terminal.set_status(f"Shell set to {selected}")
        if self._terminal_visible:
            self._on_terminal_restart()
        self._request_ui_refresh()

    def _on_terminal_clear(self) -> None:
        self.terminal.clear_output()
        if self._terminal_process is not None:
            self._terminal_process.clear_render()
        self._request_ui_refresh()

    def _on_terminal_restart(self) -> None:
        self._stop_terminal_process()
        self._ensure_terminal_process()
        if self._terminal_process is not None:
            self.terminal.set_status(f"Restarted ({self._terminal_process.active_shell})")
            self._emit_terminal_output(f"\r\n[terminal] restarted with shell={self._terminal_process.active_shell}\r\n")
        self._request_ui_refresh()

    def _on_send(self, event=None) -> None:
        text = self._extract_event_text(event).strip()
        if not text:
            text = self.chat_page.get_composer_text()
        if not text:
            return

        self.chat_page.add_user_message(text, self.page.session)
        self.chat_page.clear_composer()

        if not self.current_session_id:
            self.chat_page.set_status("No active session")
            self._request_ui_refresh()
            return

        self.chat_page.set_status("Waiting for response...")
        self.chat_page.set_context_info("Backend: Ollama")
        self._request_ui_refresh()

        self._send_runtime(
            "chat.send",
            {
                "session_id": self.current_session_id,
                "message": {"role": "user", "content": [{"type": "text", "text": text}]},
            },
            intent="chat.send",
        )
        self._cache_active_session_state()

    def _on_new_chat(self, event=None) -> None:
        _ = event
        self.chat_page.set_status("Creating new conversation...")
        self._request_ui_refresh()
        self._cache_active_session_state()
        self._send_runtime("session.create", {"title": "New Conversation"}, intent="session.create")

    def _on_refresh_sessions(self, event=None) -> None:
        _ = event
        self.chat_page.set_status("Refreshing conversations...")
        self._request_ui_refresh()
        self._send_runtime("session.list", {}, intent="session.list")

    def _open_session(self, session_id: str) -> None:
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

    def _on_runtime_message(self, message: dict[str, Any]) -> None:
        if "id" in message and "result" in message:
            self._handle_response(message.get("id"), message["result"])
            return

        if "id" in message and "error" in message:
            err = message.get("error", {})
            msg = err.get("message") if isinstance(err, dict) else str(err)
            self.chat_page.set_status(f"Runtime error: {msg}")
            self.settings_page.set_runtime_status(f"Runtime error: {msg}")
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
                text = "".join(part.get("text", "") for part in content if isinstance(part, dict))
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

    def _handle_response(self, request_id: int | None, result: dict[str, Any]) -> None:
        request_meta = self._request_meta.pop(request_id, {}) if isinstance(request_id, int) else {}
        request_intent = str(request_meta.get("intent", ""))
        requested_session_id = str(request_meta.get("session_id", "")).strip()

        if request_intent == "runtime.info":
            backend = str(result.get("backend", "ollama")).strip().title()
            model = str(result.get("model", "")).strip()
            self.chat_page.set_runtime_label(f"Runtime: {backend} ({model})" if model else f"Runtime: {backend}")
            self.settings_page.set_runtime_status(f"Runtime info loaded ({backend})")
            self._request_ui_refresh()
            return

        if request_intent == "runtime.health":
            self.settings_page.set_runtime_health(result)
            self._request_ui_refresh()
            return

        if "sessions" in result:
            self._sessions = result.get("sessions", [])
            if not self.current_session_id and self._sessions:
                self.current_session_id = self._sessions[0].get("id")
            self.sidebar.set_sessions(self._sessions, self.current_session_id)
            self._request_ui_refresh()
            if not self._sessions:
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
            session_id = result.get("session_id")
            title = result.get("title", "New Conversation")
            new_session = {"id": session_id, "title": title}
            if not any(s.get("id") == session_id for s in self._sessions):
                self._sessions.insert(0, new_session)

            self.current_session_id = session_id
            self.sidebar.set_sessions(self._sessions, session_id)
            self.chat_page.set_title(title)
            self.chat_page.clear_messages(self.page.session)
            self._session_view_cache[session_id] = {"title": title, "messages": []}
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
                return
            opened_session_id = str(result.get("session_id", self.current_session_id or "")).strip()
            if opened_session_id and self.current_session_id and opened_session_id != self.current_session_id:
                return

            self.chat_page.clear_messages(self.page.session)
            title = result.get("title", "Genesis")
            self.chat_page.set_title(title)
            for item in result.get("messages", []):
                role = item.get("role", "assistant")
                content = item.get("content", [])
                text = ""
                if isinstance(content, list):
                    text = "".join(part.get("text", "") for part in content if isinstance(part, dict))
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

    def _send_runtime(
        self,
        method: str,
        params: dict[str, Any],
        *,
        intent: str,
        meta: dict[str, Any] | None = None,
    ) -> None:
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

    @staticmethod
    def _sanitize_user_display_text(text: str) -> str:
        if not text:
            return ""
        if "[Genesis Source Context Start]" not in text:
            return text
        marker = "User request:\n"
        if marker in text:
            return text.split(marker, 1)[1].strip()
        return text

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
        configured = str(self.settings.preferred_shell or "").strip()
        if configured:
            return configured
        env_value = os.environ.get("GENESIS_SHELL")
        if env_value and env_value.strip():
            return env_value.strip()
        return "auto"

    def _ensure_terminal_process(self) -> None:
        if self._terminal_process is not None and self._terminal_process.is_running():
            return
        process = TerminalProcess(
            workspace_root=self.paths.root,
            on_output=None,
            on_screen=self._render_terminal_screen,
            on_closed=self._on_terminal_process_closed,
            preferred_shell=self._preferred_shell or None,
        )
        if process.start():
            self._terminal_process = process
            self.terminal.set_status(f"Running ({process.active_shell})")
        else:
            self._terminal_process = None
            self.terminal.set_status("Failed to start")

    def _stop_terminal_process(self) -> None:
        process = self._terminal_process
        self._terminal_process = None
        if process is not None:
            process.stop()

    def _render_terminal_screen(self, frame: str) -> None:
        def _push() -> None:
            self.terminal.render_screen(self.page.session, frame)
            try:
                self.page.update()
            except Exception:
                pass

        if self._ui_loop is None:
            _push()
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is self._ui_loop:
            _push()
            return

        try:
            self._ui_loop.call_soon_threadsafe(_push)
        except Exception:
            _push()

    def _emit_terminal_output(self, text: str) -> None:
        if not text:
            return
        def _push() -> None:
            process = self._terminal_process
            if process is not None and process.is_running():
                process.inject_output(text)
            else:
                self.terminal.send_output(self.page.session, text)
            try:
                self.page.update()
            except Exception:
                pass

        if self._ui_loop is None:
            _push()
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is self._ui_loop:
            _push()
            return

        try:
            self._ui_loop.call_soon_threadsafe(_push)
        except Exception:
            _push()

    def _on_terminal_process_closed(self, exit_code: int | None) -> None:
        self._terminal_process = None
        self.terminal.set_status(f"Closed ({exit_code})")
        self._emit_terminal_output(f"\r\nShell process closed ({exit_code}).\r\n")

    @staticmethod
    def _extract_event_text(event: Any) -> str:
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
