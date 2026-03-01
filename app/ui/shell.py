"""Genesis Studio Shell — the main application window.

Launches the Genesis Runtime in a background thread, connects via WebSocket,
and wires the ButterflyUI components to the live message bus.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any

import butterflyui as ui

from app.utils import read_text_file, render_template, json_for_script_tag
from app.ui.sidebar_view import SidebarView
from app.ui.chat_page import ChatPage
from app.ui.terminal_container import TerminalContainer


# ── Runtime Bridge ───────────────────────────────────────────────────

class RuntimeBridge:
    """Manages the Genesis Runtime process and WebSocket connection.

    Runs the runtime in a background thread and provides an async bridge
    for the ButterflyUI app to send/receive JSON-RPC messages.
    """

    def __init__(self, on_message=None) -> None:
        self._ws = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._on_message = on_message
        self._connected = threading.Event()
        self._runtime = None

    def start(self) -> None:
        """Launch runtime + client in a background thread."""
        self._thread = threading.Thread(target=self._run_thread, daemon=True)
        self._thread.start()

    def _run_thread(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._start_runtime_and_connect())

    async def _start_runtime_and_connect(self) -> None:
        # Import here to avoid circular imports
        from genesis.core.ws_server import GenesisRuntime

        # Start the runtime server
        self._runtime = GenesisRuntime(db_path="data/genesis.sqlite")
        import websockets
        server = await websockets.serve(
            self._runtime._ws_handler, "127.0.0.1", 8765
        )

        # Connect as a client
        self._ws = await websockets.connect("ws://127.0.0.1:8765")
        self._connected.set()

        # Listen for messages from the runtime
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if self._on_message:
                    self._on_message(msg)
        except Exception:
            pass

    def send(self, method: str, params: dict, msg_id: int | None = 1) -> None:
        """Send a JSON-RPC request to the runtime (thread-safe)."""
        if self._ws is None or self._loop is None:
            return
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params,
        }, ensure_ascii=False)

        asyncio.run_coroutine_threadsafe(self._ws.send(payload), self._loop)

    def wait_connected(self, timeout: float = 5.0) -> bool:
        return self._connected.wait(timeout)


# ── Shell ────────────────────────────────────────────────────────────

class GenesisStudioShell:
    def __init__(self, page: ui.Page, paths: Any) -> None:
        self.page = page
        self.paths = paths

        self.state = type("S", (), {"show_terminal": False})()
        self.terminal_view_html: ui.HtmlView | None = None
        self.terminal_container: TerminalContainer | None = None
        self.chat_page: ChatPage | None = None

        # Session state
        self.current_session_id: str | None = None
        self._last_delta_flush = 0.0

        # Runtime bridge
        self.bridge = RuntimeBridge(on_message=self._on_runtime_message)

    def mount(self) -> None:
        self.page.title = "Genesis Studio"
        self.render()
        # Launch the runtime in the background
        self.bridge.start()
        # Wait for connection, then initialize
        threading.Thread(target=self._init_session, daemon=True).start()

    def _init_session(self) -> None:
        """Called from a background thread after runtime connects."""
        if not self.bridge.wait_connected(timeout=5.0):
            return
        self.bridge.send("workspace.set", {"root": str(Path.cwd())}, msg_id=99)
        self.bridge.send("session.list", {}, msg_id=103)
        # Create a default session
        self.bridge.send("session.create", {"title": "New Conversation"}, msg_id=100)

    def render(self) -> None:
        self.page.root = self._build_window()
        self.page.update()

    # ── UI Building ──────────────────────────────────────────────────

    def _build_window(self) -> ui.SplitPane:
        return ui.SplitPane(
            self._build_sidebar(),
            self._build_main_panel(),
            axis="horizontal",
            initial_first_size=300,
            min_first_size=200,
            min_second_size=200,
            expand=True,
        )

    def _build_sidebar(self) -> ui.Container:
        conversations = []
        sv = SidebarView(conversations=conversations, width=300)
        sv.on_select(self._on_sidebar_select)
        sv.on_new(self._on_new_conversation)
        self._sidebar_view = sv
        return sv.build()

    def _build_main_panel(self) -> ui.Column:
        chat = ChatPage(self.page, self.paths)
        self.chat_page = chat
        chat.on_send(self._send_message)
        chat.on_toggle_terminal(self._toggle_terminal)

        # Toolbar with terminal icon button
        toolbar = ui.Container(
            ui.Row(
                ui.Spacer(),
                ui.Button(
                    text="🖥️",
                    variant="text",
                    bgcolor="#4F46E5",
                    on_click=self._toggle_terminal,
                    width=44,
                ),
            ),
            padding=6,
        )

        return ui.Column(toolbar, chat.build(), spacing=6, expand=True)

    # ── Sidebar Events ───────────────────────────────────────────────

    def _on_sidebar_select(self, conv_id: str) -> None:
        self.current_session_id = conv_id
        self.bridge.send("session.open", {"session_id": conv_id}, msg_id=101)

    def _on_new_conversation(self) -> None:
        self.bridge.send("session.create", {"title": "New Conversation"}, msg_id=102)

    # ── Chat Events ──────────────────────────────────────────────────

    def _send_message(self, text: str | None = None) -> None:
        if self.chat_page is None:
            return

        if text is None:
            text = getattr(self.chat_page.composer, "value", None) or \
                   getattr(self.chat_page.composer, "text", None)
        if not text or not text.strip():
            return

        # Show user message in UI immediately
        self.chat_page.add_user_message(text.strip())
        self.chat_page.clear_composer()
        self.page.update()

        # Send to runtime
        if self.current_session_id:
            self.bridge.send("chat.send", {
                "session_id": self.current_session_id,
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": text.strip()}],
                },
            }, msg_id=200)
            self.bridge.send("ui.event", {
                "type": "chat.send",
                "payload": {
                    "session_id": self.current_session_id,
                    "chars": len(text.strip()),
                },
            }, msg_id=None)

    # ── Runtime Message Handler ──────────────────────────────────────

    def _on_runtime_message(self, msg: dict) -> None:
        """Called from the bridge thread when a message arrives from the runtime."""
        # Handle JSON-RPC responses (have "id")
        msg_id = msg.get("id")
        if msg_id is not None and "result" in msg:
            self._handle_response(msg_id, msg["result"])
            return

        # Handle notifications (have "method")
        method = msg.get("method")
        params = msg.get("params", {})
        if method is None:
            return

        if method == "chat.begin":
            mid = params.get("message_id", "")
            if self.chat_page:
                self.chat_page.begin_streaming(mid)
                self.page.update()

        elif method == "chat.delta":
            mid = params.get("message_id", "")
            delta = params.get("delta", "")
            if self.chat_page:
                self.chat_page.add_delta(mid, delta)
                now = time.monotonic()
                if (now - self._last_delta_flush) >= 0.04:
                    self._last_delta_flush = now
                    self.page.update()

        elif method == "chat.message":
            message = params.get("message", {})
            mid = message.get("id", "")
            content = message.get("content", [])
            full_text = ""
            if isinstance(content, list):
                full_text = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
            if self.chat_page:
                self.chat_page.finalize_message(mid, full_text)
                self.page.update()

        elif method == "tool.call":
            tool_name = params.get("tool", "")
            if self.terminal_container is not None:
                self.terminal_container.send_output(
                    self.page.session,
                    f"\r\n[tool.call] {tool_name}\r\n",
                )

        elif method == "tool.result":
            tool_id = params.get("id", "")
            ok = params.get("ok", False)
            status = "ok" if ok else "error"
            if self.terminal_container is not None:
                self.terminal_container.send_output(
                    self.page.session,
                    f"[tool.result] {tool_id} {status}\r\n",
                )

        elif method == "session.updated":
            # Refresh sidebar
            self.bridge.send("session.list", {}, msg_id=103)

        elif method == "log.append":
            line = params.get("line", "")
            print(f"[Genesis] {line}")

    def _handle_response(self, msg_id: int, result: dict) -> None:
        """Handle JSON-RPC responses to our requests."""
        if msg_id == 100 or msg_id == 102:
            # session.create response
            sid = result.get("session_id")
            if sid:
                self.current_session_id = sid
                if self.chat_page:
                    title = result.get("title", "New Conversation")
                    self.chat_page.set_title(title)
                    self.page.update()
                # Refresh sidebar
                self.bridge.send("session.list", {}, msg_id=103)

        elif msg_id == 103:
            # session.list response
            sessions = result.get("sessions", [])
            if hasattr(self, "_sidebar_view"):
                self._sidebar_view.set_conversations([
                    {"id": s["id"], "title": s["title"]}
                    for s in sessions
                ])
                self.page.update()

        elif msg_id == 101:
            # session.open response — load messages into chat
            messages = result.get("messages", [])
            if self.chat_page:
                title = result.get("title")
                if isinstance(title, str) and title.strip():
                    self.chat_page.set_title(title)
                # Clear existing messages
                self.chat_page.chat_thread.children.clear()
                for m in messages:
                    role = m.get("role", "user")
                    content = m.get("content", [])
                    text = ""
                    if isinstance(content, list):
                        text = " ".join(
                            p.get("text", "") for p in content if isinstance(p, dict)
                        )
                    if role == "user":
                        self.chat_page.add_user_message(text)
                    elif role == "assistant":
                        self.chat_page.add_assistant_message(text)
                self.page.update()

        elif msg_id == 300:
            if self.terminal_container is None:
                return
            if result.get("ok"):
                data = result.get("result", {})
                rendered = json.dumps(data, ensure_ascii=False, indent=2)
                self.terminal_container.send_output(
                    self.page.session,
                    f"{rendered}\r\n",
                )
            else:
                self.terminal_container.send_output(
                    self.page.session,
                    f"ERROR: {result.get('error', 'unknown')}\r\n",
                )

    # ── Terminal ─────────────────────────────────────────────────────

    def _on_terminal_message(self, msg: dict[str, Any]) -> None:
        payload = msg.get("payload", msg)
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {"type": "raw", "data": payload}

        if not isinstance(payload, dict):
            return

        event_type = payload.get("type", "terminal.unknown")
        self.bridge.send("ui.event", {
            "type": f"terminal.{event_type}",
            "payload": payload,
        }, msg_id=None)

        if event_type == "input":
            command = str(payload.get("data", "")).strip()
            if command:
                self.bridge.send("tool.call", {
                    "tool": "fs.list",
                    "args": {"root": "." if command == "ls" else command},
                }, msg_id=300)

    def _start_terminal_process(self, html_view: ui.HtmlView | None) -> None:
        try:
            if html_view is not None:
                html_view.invoke(
                    self.page.session,
                    "postMessage",
                    {"payload": {"type": "output", "data": "Welcome to Genesis Shell\r\n"}},
                )
        except Exception:
            pass

    def _toggle_terminal(self, event=None) -> None:
        if not self.state.show_terminal:
            self.state.show_terminal = True
            if self.terminal_container is None:
                self.terminal_container = TerminalContainer(self.paths)
                view = self.terminal_container.build()
                self.terminal_view_html = view
                view.on_event(self.page.session, "message", self._on_terminal_message)
            else:
                view = self.terminal_view_html

            try:
                if self.chat_page is not None and view is not None:
                    self.chat_page.attach_terminal(view)
                    self.page.update()
            except Exception:
                pass

            try:
                def do_open():
                    if self.terminal_container is not None and self.page is not None:
                        self.terminal_container.open(self.page.session)
                        self.page.update()

                threading.Timer(0.05, do_open).start()
            except Exception:
                pass

            self._start_terminal_process(self.terminal_view_html)
        else:
            self.state.show_terminal = False
            try:
                if self.terminal_container is not None:
                    self.terminal_container.close(self.page.session)
                    self.page.update()
            except Exception:
                pass
            threading.Timer(0.4, self._delayed_detach).start()

    def _delayed_detach(self) -> None:
        try:
            if not self.state.show_terminal:
                if self.chat_page is not None:
                    self.chat_page.detach_terminal()
                self.page.update()
        except Exception:
            pass
