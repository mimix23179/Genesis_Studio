from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import threading
import time
from itertools import count
from pathlib import Path
from typing import Any

import butterflyui as ui
import cv2
import websockets

from app.config import AppPaths, RuntimeSettings, load_runtime_settings, resolve_paths
from genesis.backend import OllamaDownloadManager, OllamaLibraryService, OllamaRuntime
from genesis.astrea import AstreaService
from genesis.backend.ollama_bootstrap import OllamaWorkspaceBootstrap
from .astrea_page import AstreaPage
from .theme import build_palette, build_stylesheet
from .chat_page import ChatPage
from .downloads_page import DownloadsPageView
from .ide_page import IDEPage
from .models_page import ModelsPage
from .settings_page import SettingsPage
from .sidebar_view import AstreaSidebar, Conversations, DownloadsSidebar, ExplorerSidebar, ModelsSidebar, SettingsSidebar

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

            try:
                self._ws = await websockets.connect(endpoint, open_timeout=0.75)
                self._runtime_port = port
                self._connected.set()
                await self._recv_loop()
                return
            except Exception:
                self._ws = None

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
    """Top-level app controller wiring UI, runtime, and settings."""

    _BG = "#F4F6FB"
    _BG_DARK = "#0F1118"
    _SURFACE = "#FFFFFF"
    _SURFACE_ALT = "#F8FAFC"
    _BORDER = "#CBD5E1"
    _TEXT = "#0F172A"
    _MUTED = "#64748B"
    _ACCENT = "#10A37F"
    _ON_ACCENT = "#FFFFFF"
    _SUCCESS = "#047857"
    _ERROR = "#B91C1C"

    def __init__(self, page: ui.Page, paths: AppPaths | None = None) -> None:
        self.page = page
        self.paths = paths or resolve_paths()
        self.settings = load_runtime_settings(self.paths.settings_file)
        self._theme_mode = "dark"

        self.chat_page = ChatPage()
        self.ide_page = IDEPage()
        self.models_page = ModelsPage()
        self.downloads_page = DownloadsPageView()
        self.settings_page = SettingsPage(self.paths.settings_file)
        self.astrea_page = AstreaPage(self.paths.root)
        self.conversations = Conversations(width=280)
        self.explorer_sidebar = ExplorerSidebar(width=280)
        self.settings_sidebar = SettingsSidebar(width=280)
        self.models_sidebar = ModelsSidebar(width=280)
        self.downloads_sidebar = DownloadsSidebar(width=280)
        self.astrea_sidebar = AstreaSidebar()
        self.astrea_service = AstreaService(self.paths.root, self.paths.data_root)

        self.current_session_id: str | None = None
        self._sessions: list[dict[str, Any]] = []
        self._request_ids = count(100)
        self._request_meta: dict[int, dict[str, Any]] = {}
        self._session_view_cache: dict[str, dict[str, Any]] = {}
        self._last_delta_refresh = 0.0
        self._ui_loop: asyncio.AbstractEventLoop | None = None
        self._active_view = "chat"
        self._active_view_opacity = {
            "chat": 1.0,
            "ide": 0.0,
            "astrea": 0.0,
            "models": 0.0,
            "downloads": 0.0,
            "settings": 0.0,
        }
        self._downloads_banner = "No active downloads"
        self._download_history: list[dict[str, Any]] = []
        self._settings_sidebar_section = "appearance"
        self._ide_open_file: str = ""
        self._ide_state_poll_inflight = False

        self._llm_drawer_open = False
        self._active_model = str(self.settings.model or "").strip() or "qwen2.5-coder:7b"
        self._selected_model = self._active_model
        self._available_models: list[str] = []
        self._catalog_entries: list[dict[str, Any]] = []
        self._catalog_page = 1
        self._catalog_page_size = 8
        self._current_model_detail: dict[str, Any] | None = None
        self._selected_pull_target = ""

        self._asset_server: ui.AssetServer | None = None
        self._background_cache_dir = self.paths.root / "data" / "background_cache"
        self._background_image_path = self.settings_page.get_background_path()
        self._background_asset_url = ""
        self._background_refresh_timer: threading.Timer | None = None
        self._background_refresh_token = 0
        self._accent_color = self.settings_page.get_accent_color()
        self._palette = build_palette(self._accent_color)
        self._ollama_library = OllamaLibraryService()
        self._download_manager = OllamaDownloadManager(
            timeout=max(300.0, self.settings.request_timeout * 8.0),
            on_update=self._on_download_update,
        )

        self._ollama_bootstrap = OllamaWorkspaceBootstrap(
            workspace_root=self.paths.root,
            ollama_base_url=self.settings.ollama_base_url,
            model=self._active_model,
            models_dir=self.settings.ollama_models_dir,
            auto_pull=False,
            request_timeout=self.settings.request_timeout,
        )

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
        self._refresh_stylesheet()
        self.page.bgcolor = self._BG

        self.conversations.on_new(self._on_new_chat)
        self.conversations.on_select(self._open_session)
        self.conversations.on_refresh(self._on_refresh_sessions)

        self.page.root = self._build_root()
        self._apply_theme(self._read_theme_value())
        self._apply_accent(self._accent_color, persist=False)
        self._apply_background_image(self._background_image_path, persist=False)

        session = self.page.session
        self.chat_page.composer.on_submit(session, self._on_send)
        self.chat_page.composer.on_change(session, self.chat_page.on_composer_change)
        self.chat_page.send_button.on_click(session, self._on_send)
        self.ide_page.bind_events(session)
        self.ide_page.on_save(self._on_ide_save_requested)
        self.models_page.bind_events(
            session,
            on_refresh=self._on_models_refresh,
            on_page_change=self._on_models_page_change,
            on_open_model=self._open_model_detail,
            on_back=self._on_model_detail_back,
            on_pull=self._on_model_pull,
            on_variant_change=self._on_model_variant_change,
        )
        self.downloads_page.bind_events(
            session,
            on_refresh=self._on_downloads_refresh,
            on_pause=self._on_download_pause,
            on_resume=self._on_download_resume,
        )
        self.astrea_page.bind_events(
            session,
            on_refresh=self._on_astrea_refresh,
            on_generate=self._on_astrea_generate,
            on_train=self._on_astrea_train,
            on_caption=self._on_astrea_caption,
            on_build_dataset=self._on_astrea_build_dataset,
            on_cancel=self._on_astrea_cancel,
            on_mode_change=self._on_astrea_mode_change,
        )
        self.astrea_sidebar.bind_events(
            session,
            on_refresh=self._on_astrea_refresh,
            on_cancel=self._on_astrea_cancel,
            on_switch_mode=self._on_astrea_mode_change,
        )
        self.astrea_service.set_on_update(self._on_astrea_service_update)

        self.settings_page.bind_events(
            session,
            self._on_theme_change,
            on_runtime_save=self._on_runtime_save,
            on_runtime_health=self._on_runtime_health_request,
            on_accent_change=self._on_accent_change,
            on_accent_overlay_open=self._open_accent_overlay,
            on_accent_overlay_close=self._close_accent_overlay,
            on_background_result=self._on_background_result,
            on_background_clear=self._on_background_clear,
            on_background_opacity_change=self._on_background_opacity_change,
            on_background_blur_change=self._on_background_blur_change,
            on_translucent_panels_change=self._on_translucent_panels_change,
        )
        self.conversations.bind_events(session)
        self.explorer_sidebar.bind_events(session)
        self.settings_sidebar.bind_events(session)
        self.models_sidebar.bind_events(session)
        self.downloads_sidebar.bind_events(session)
        self.explorer_sidebar.on_refresh(self._on_explorer_refresh)
        self.explorer_sidebar.on_select_file(self._on_explorer_file_select)
        self.settings_sidebar.on_select(self._on_settings_sidebar_select)
        self.models_sidebar.on_refresh(self._on_models_refresh)
        self.models_sidebar.on_select_model(self._on_models_sidebar_select)
        self.downloads_sidebar.on_refresh(self._on_downloads_refresh)

        self._ide_toggle.on_click(session, self._toggle_ide)
        self._settings_toggle.on_click(session, self._toggle_settings)
        self._models_toggle.on_click(session, self._toggle_models)
        self._downloads_toggle.on_click(session, self._toggle_downloads)
        self._astrea_toggle.on_click(session, self._toggle_astrea)
        self._chat_toggle.on_click(session, self._toggle_chat)
        self._llm_toggle.on_click(session, self._toggle_llm_drawer)
        self._llm_model_select.on_change(session, self._on_llm_model_change, inputs=[self._llm_model_select])
        self._llm_refresh_button.on_click(session, self._on_llm_refresh)
        self._llm_use_button.on_click(session, self._on_llm_use_model)
        self._llm_load_button.on_click(session, self._on_llm_load_model)
        self._llm_unload_button.on_click(session, self._on_llm_unload_model)
        self._llm_drawer_close_button.on_click(session, self._on_llm_close_button)
        self._llm_drawer.on_event(session, "close", self._on_llm_drawer_closed)
        self._sync_explorer_sidebar()
        self._sync_settings_sidebar()
        self._sync_models_sidebar()
        self._sync_downloads_sidebar()
        self._sync_astrea_sidebar()
        self._apply_active_view()
        self._render_downloads_page()
        self._open_initial_ide_file()
        self._schedule_ide_state_sync(0.9)
        self._request_ui_refresh()

        self.bridge.start()
        self.astrea_service.refresh()
        threading.Thread(target=self._post_connect_init, daemon=True).start()

    def _build_root(self):
        self._ide_toggle = ui.GlyphButton(
            glyph="braces",
            tooltip="IDE",
            class_name="gs-rail",
            events=["click"],
            radius=12,
            size="20",
            width=40,
            height=40,
        )
        self._settings_toggle = ui.GlyphButton(
            glyph="settings",
            tooltip="Settings",
            class_name="gs-rail",
            events=["click"],
            radius=12,
            size="20",
            width=40,
            height=40,
        )
        self._models_toggle = ui.GlyphButton(
            glyph="extension",
            tooltip="Models",
            class_name="gs-rail",
            events=["click"],
            radius=12,
            size="20",
            width=40,
            height=40,
        )
        self._astrea_toggle = ui.GlyphButton(
            glyph="image",
            tooltip="Astrea",
            class_name="gs-rail",
            events=["click"],
            radius=12,
            size="20",
            width=40,
            height=40,
        )
        self._downloads_toggle = ui.GlyphButton(
            glyph="download",
            tooltip="Downloads",
            class_name="gs-rail",
            events=["click"],
            radius=12,
            size="20",
            width=40,
            height=40,
        )
        self._llm_toggle = ui.Button(
            text="Installed",
            icon="inventory",
            tooltip="Installed Models",
            class_name="gs-button gs-outline gs-pill",
            variant="outlined",
            events=["click"],
            font_size=12,
            font_weight="700",
            radius=999,
            content_padding={"left": 14, "right": 14, "top": 4, "bottom": 4},
        )
        self._nav_rail_surface: ui.Surface | None = None
        self._chat_toggle = ui.GlyphButton(
            glyph="chat",
            tooltip="Chat",
            class_name="gs-rail",
            events=["click"],
            radius=12,
            size="20",
            width=40,
            height=40,
        )
        self._accent_chip = ui.Color(
            value=self._accent_color,
            show_hex=False,
            show_label=False,
            width=18,
            height=18,
            radius=99,
            border_color=self._BORDER,
            border_width=1,
        )
        self._toolbar_status = ui.Text("Ready", font_size=12, color=self._MUTED)
        self._toolbar_surface: ui.Surface | None = None
        self._llm_drawer_surface: ui.Surface | None = None
        self._llm_drawer_close_button: ui.Button | None = None
        self._llm_model_summary = ui.Text("Pull a model from the library, then load it here.", font_size=11, color=self._MUTED)
        self._llm_model_count = ui.Text("0 installed", font_size=11, color=self._MUTED)

        self._nav_rail_surface = ui.Surface(
            ui.Column(
                ui.Container(self._chat_toggle, padding={"top": 10, "bottom": 6}),
                ui.Container(self._ide_toggle, padding={"top": 6, "bottom": 6}),
                ui.Container(self._settings_toggle, padding={"top": 6, "bottom": 6}),
                ui.Container(self._models_toggle, padding={"top": 6, "bottom": 6}),
                ui.Container(self._astrea_toggle, padding={"top": 6, "bottom": 6}),
                ui.Container(self._downloads_toggle, padding={"top": 6, "bottom": 6}),
                ui.Spacer(),
                spacing=0,
                cross_axis="center",
                expand=True,
            ),
            width=56,
            class_name="gs-shell-rail",
            padding={"left": 8, "right": 8, "top": 10, "bottom": 10},
            style={"border_right": f"1px solid {self._BORDER}"},
        )

        self._toolbar_surface = ui.Surface(
            ui.Row(
                ui.Spacer(),
                self._llm_toggle,
                ui.Spacer(),
                self._accent_chip,
                self._toolbar_status,
                spacing=8,
                cross_axis="center",
            ),
            padding={"left": 12, "right": 12, "top": 6, "bottom": 6},
            class_name="gs-toolbar",
            style={"overflow": "hidden"},
        )
        toolbar = self._toolbar_surface

        self._chat_sidebar_view = ui.Container(self.conversations.build(), width=280, visible=True, opacity=1.0, animate=True, duration_ms=220)
        self._ide_sidebar_view = ui.Container(self.explorer_sidebar.build(), width=280, visible=False, opacity=0.0, animate=True, duration_ms=220)
        self._settings_sidebar_view = ui.Container(self.settings_sidebar.build(), width=280, visible=False, opacity=0.0, animate=True, duration_ms=220)
        self._models_sidebar_view = ui.Container(self.models_sidebar.build(), width=280, visible=False, opacity=0.0, animate=True, duration_ms=220)
        self._astrea_sidebar_view = ui.Container(self.astrea_sidebar.build(), width=280, visible=False, opacity=0.0, animate=True, duration_ms=220)
        self._downloads_sidebar_view = ui.Container(self.downloads_sidebar.build(), width=280, visible=False, opacity=0.0, animate=True, duration_ms=220)
        self._sidebar_stack = ui.Stack(
            self._chat_sidebar_view,
            self._ide_sidebar_view,
            self._settings_sidebar_view,
            self._models_sidebar_view,
            self._astrea_sidebar_view,
            self._downloads_sidebar_view,
            fit="expand",
            expand=True,
        )

        self.chat_view = ui.Container(self.chat_page.build(), expand=True, visible=True, opacity=1.0, animate=True, duration_ms=220)
        self.ide_view = ui.Container(self.ide_page.build(), expand=True, visible=False, opacity=0.0, animate=True, duration_ms=220)
        self.models_view = ui.Container(self.models_page.build(), expand=True, visible=False, opacity=0.0, animate=True, duration_ms=220)
        self.astrea_view = ui.Container(self.astrea_page.build(), expand=True, visible=False, opacity=0.0, animate=True, duration_ms=220)
        self.downloads_view = ui.Container(self.downloads_page.build(), expand=True, visible=False, opacity=0.0, animate=True, duration_ms=220)
        self.settings_view = ui.Container(self.settings_page.build(), expand=True, visible=False, opacity=0.0, animate=True, duration_ms=220)
        self._chat_stack = ui.Stack(
            self.chat_view,
            self.ide_view,
            self.models_view,
            self.astrea_view,
            self.downloads_view,
            self.settings_view,
            fit="expand",
            expand=True,
        )

        self._llm_model_select = ui.Select(
            label="Available Models",
            class_name="gs-input",
            value=self._selected_model,
            options=[{"label": self._selected_model, "value": self._selected_model}],
            events=["change"],
            width=420,
        )
        self._llm_refresh_button = ui.Button(
            text="Refresh",
            class_name="gs-button gs-outline",
            variant="outlined",
            events=["click"],
        )
        self._llm_use_button = ui.Button(
            text="Use Model",
            class_name="gs-button gs-primary",
            variant="filled",
            events=["click"],
            radius=10,
            font_weight="700",
        )
        self._llm_load_button = ui.Button(
            text="Load",
            class_name="gs-button gs-outline",
            variant="outlined",
            events=["click"],
        )
        self._llm_unload_button = ui.Button(
            text="Unload",
            class_name="gs-button gs-outline",
            variant="outlined",
            events=["click"],
        )
        self._llm_status = ui.Text("Model drawer idle", font_size=12, color=self._MUTED)
        self._llm_drawer_close_button = ui.Button(
            text="X",
            class_name="gs-button gs-outline gs-pill",
            variant="outlined",
            events=["click"],
            radius=999,
            width=44,
            height=44,
            font_weight="700",
        )

        self._llm_drawer_surface = ui.Surface(
            ui.Column(
                ui.Row(
                    ui.Icon(icon="model_training", size=18, color=self._TEXT),
                    ui.Text("Installed Runtime Models", font_size=15, font_weight="700", color=self._TEXT),
                    ui.Spacer(),
                    self._llm_model_count,
                    spacing=8,
                    cross_axis="center",
                ),
                self._llm_model_summary,
                self._llm_model_select,
                ui.Row(
                    self._llm_refresh_button,
                    self._llm_use_button,
                    self._llm_load_button,
                    self._llm_unload_button,
                    spacing=8,
                ),
                self._llm_status,
                spacing=10,
            ),
            padding={"left": 18, "right": 18, "top": 18, "bottom": 18},
            class_name="gs-drawer",
            style={"overflow": "hidden"},
        )
        self._llm_drawer = ui.Overlay(
            child=ui.Container(
                ui.Row(
                    ui.Column(
                        ui.Container(self._llm_drawer_surface, width=760),
                        self._llm_drawer_close_button,
                        spacing=12,
                        cross_axis="center",
                    ),
                    main_axis="center",
                    cross_axis="center",
                    expand=True,
                ),
                width="100%",
                padding=24,
                expand=True,
            ),
            open=False,
            dismissible=True,
            scrim_color=self._palette["overlay_scrim"],
            alignment="center",
            transition_type="fade",
            transition_ms=220,
            events=["close"],
        )

        content = ui.Column(
            toolbar,
            ui.Expanded(self._chat_stack),
            spacing=8,
            expand=True,
        )
        main_row = ui.Row(
            self._nav_rail_surface,
            ui.Container(self._sidebar_stack, width=280, expand=False),
            ui.Expanded(content),
            expand=True,
            spacing=0,
        )

        self._workspace_layer = ui.Container(
            main_row,
            expand=True,
            class_name="gs-workspace-root",
            style=self._build_workspace_style(),
            clip_behavior="anti_alias",
        )

        return ui.Stack(
            self._workspace_layer,
            self.settings_page.get_accent_overlay(),
            self._llm_drawer,
            fit="expand",
            expand=True,
        )

    def _post_connect_init(self) -> None:
        if not self.bridge.wait_connected(10.0):
            self.chat_page.set_status("Runtime unavailable")
            self.models_page.set_status("Runtime unavailable", error=True)
            self.downloads_page.set_status("Runtime unavailable", error=True)
            self.settings_page.set_runtime_status("Runtime unavailable")
            self._toolbar_status.patch(text="Runtime unavailable", color="#B91C1C")
            self._request_ui_refresh()
            return

        self.chat_page.set_status("Preparing Ollama service...")
        self.models_page.set_status("Connecting to Ollama library...")
        self.settings_page.set_runtime_status("Preparing Ollama service...")
        self._toolbar_status.patch(text="Preparing Ollama service...", color=self._MUTED)
        self._request_ui_refresh()

        runtime_port = self.bridge.runtime_port
        status = f"Connected - port {runtime_port}" if runtime_port else "Connected"
        self.chat_page.set_status(status)
        self.settings_page.set_runtime_status(f"{status} | preparing Ollama service...")
        threading.Thread(
            target=lambda: self._prepare_ollama_model_store(announce=True),
            daemon=True,
        ).start()

        self._send_runtime("session.list", {}, intent="session.list.bootstrap")
        self._send_runtime("workspace.set", {"root": str(Path.cwd())}, intent="workspace.set")
        self._send_runtime("runtime.info", {}, intent="runtime.info")
        self._send_runtime("runtime.health", {}, intent="runtime.health")
        self._send_runtime("runtime.models.list", {}, intent="runtime.models.list")

    def _toggle_settings(self, event=None) -> None:
        _ = event
        self._active_view = "settings"
        self._sync_settings_sidebar()
        self._apply_active_view()
        self._request_ui_refresh()

    def _toggle_models(self, event=None) -> None:
        _ = event
        self._active_view = "models"
        if self._active_view == "models" and not self._catalog_entries:
            self.models_page.set_status("Loading Ollama library...")
            self._refresh_models_catalog(force=False)
        self._sync_models_sidebar()
        self._apply_active_view()
        self._request_ui_refresh()

    def _toggle_astrea(self, event=None) -> None:
        _ = event
        self._active_view = "astrea"
        self._sync_astrea_sidebar()
        self._apply_active_view()
        self._request_ui_refresh()

    def _toggle_downloads(self, event=None) -> None:
        _ = event
        self._active_view = "downloads"
        self._render_downloads_page()
        self._sync_downloads_sidebar()
        self._apply_active_view()
        self._request_ui_refresh()

    def _toggle_chat(self, event=None) -> None:
        _ = event
        self._active_view = "chat"
        self._apply_active_view()
        self._request_ui_refresh()

    def _toggle_ide(self, event=None) -> None:
        _ = event
        self._active_view = "ide"
        self._sync_explorer_sidebar()
        self._apply_active_view()
        self._request_ui_refresh()

    def _apply_active_view(self) -> None:
        targets = {
            "chat": self.chat_view,
            "ide": self.ide_view,
            "models": self.models_view,
            "astrea": self.astrea_view,
            "downloads": self.downloads_view,
            "settings": self.settings_view,
        }
        sidebar_targets = {
            "chat": self._chat_sidebar_view,
            "ide": self._ide_sidebar_view,
            "models": self._models_sidebar_view,
            "astrea": self._astrea_sidebar_view,
            "downloads": self._downloads_sidebar_view,
            "settings": self._settings_sidebar_view,
        }
        next_view = self._active_view if self._active_view in targets else "chat"
        for name, control in targets.items():
            is_target = name == next_view
            self._active_view_opacity[name] = 1.0 if is_target else 0.0
            control.patch(visible=True, opacity=self._active_view_opacity[name])
        for name, control in sidebar_targets.items():
            is_target = name == next_view
            control.patch(visible=True, opacity=1.0 if is_target else 0.0)

        def _finalize() -> None:
            for name, control in targets.items():
                control.patch(visible=name == next_view)
            for name, control in sidebar_targets.items():
                control.patch(visible=name == next_view)
            self._request_ui_refresh()

        self._schedule_ui_callback(0.24, _finalize)
        show_settings = next_view == "settings"
        show_models = next_view == "models"
        show_astrea = next_view == "astrea"
        show_downloads = next_view == "downloads"
        show_chat = next_view == "chat"
        show_ide = next_view == "ide"
        try:
            self._chat_toggle.patch(class_name="gs-rail gs-rail-active" if show_chat else "gs-rail")
        except Exception:
            pass
        self._ide_toggle.patch(class_name="gs-rail gs-rail-active" if show_ide else "gs-rail")
        self._settings_toggle.patch(class_name="gs-rail gs-rail-active" if show_settings else "gs-rail")
        self._models_toggle.patch(class_name="gs-rail gs-rail-active" if show_models else "gs-rail")
        self._astrea_toggle.patch(class_name="gs-rail gs-rail-active" if show_astrea else "gs-rail")
        self._downloads_toggle.patch(class_name="gs-rail gs-rail-active" if show_downloads else "gs-rail")

    def _read_theme_value(self) -> str:
        theme = "system"
        try:
            theme = str(self.settings_page.theme_select.to_dict().get("props", {}).get("value", "system")).strip()
        except Exception:
            pass
        return theme or "system"

    def _build_workspace_style(self) -> ui.Style:
        return ui.Style(
            background_layers=[
                ui.GradientWash(
                    ui.RadialGradient(
                        colors=[
                            self._palette["galaxy_primary"],
                            self._palette["bg"],
                        ],
                        center={"x": 0.48, "y": 0.22},
                        radius=0.82,
                    ),
                    position="background",
                    opacity=0.92,
                ),
                ui.GradientWash(
                    ui.RadialGradient(
                        colors=[
                            self._palette["galaxy_secondary"],
                            self._palette["bg"],
                        ],
                        center={"x": 0.78, "y": 0.72},
                        radius=0.74,
                    ),
                    position="background",
                    opacity=0.44,
                ),
                ui.OrbitField(
                    position="background",
                    opacity=0.36,
                    speed=0.28,
                    count=72,
                    radius=220,
                    band_width=180,
                    swirl=0.88,
                    marker_size=5.6,
                    palette=[
                        self._palette["galaxy_secondary"],
                        self._palette["galaxy_primary"],
                        self._palette["galaxy_hot"],
                        self._palette["galaxy_gold"],
                    ],
                    center={"x": 0.54, "y": 0.34},
                ),
                ui.ParticleField(
                    position="background",
                    opacity=0.42,
                    speed=0.38,
                    count=190,
                    spread="radial",
                    drift=0.16,
                    rotation=0.62,
                    length=11,
                    thickness=1.9,
                    palette=[
                        self._palette["galaxy_secondary"],
                        self._palette["galaxy_primary"],
                        self._palette["galaxy_hot"],
                        self._palette["galaxy_gold"],
                    ],
                    center={"x": 0.54, "y": 0.35},
                    shape="capsule",
                ),
                ui.NoiseField(
                    position="foreground",
                    opacity=0.18,
                    speed=0.08,
                    scale=1.4,
                    contrast=0.54,
                    octaves=3,
                    color=self._palette["galaxy_dust"],
                    accent_color=self._palette["galaxy_dust"],
                ),
            ],
            gradient=ui.LinearGradient(
                colors=[
                    self._palette["bg"],
                    self._palette["glass_bg"],
                ],
                begin="top_left",
                end="bottom_right",
            ),
            overflow="hidden",
        )

    def _sync_settings_sidebar(self) -> None:
        try:
            self.settings_sidebar.set_active_section(self._settings_sidebar_section)
        except Exception:
            pass

    def _sync_explorer_sidebar(self) -> None:
        try:
            self.explorer_sidebar.set_root(self.paths.root, selected_path=self._ide_open_file or None)
        except Exception:
            pass

    def _sync_models_sidebar(self) -> None:
        total_count = len(self._catalog_entries)
        page_count = max(1, math.ceil(total_count / self._catalog_page_size)) if total_count else 1
        try:
            self.models_sidebar.set_state(
                active_model=self._active_model,
                installed_models=self._available_models,
                catalog_entries=self._catalog_entries,
                current_detail=self._current_model_detail,
                catalog_page=self._catalog_page,
                catalog_page_count=page_count,
            )
        except Exception:
            pass

    def _sync_astrea_sidebar(self) -> None:
        try:
            self.astrea_sidebar.set_state(self.astrea_service.snapshot())
        except Exception:
            pass

    def _sync_downloads_sidebar(self) -> None:
        try:
            self.downloads_sidebar.set_state(
                downloads=self._download_manager.list_downloads(),
                banner=self._downloads_banner,
                completed_history=self._download_history,
            )
        except Exception:
            pass

    def _record_completed_download(self, snapshot: dict[str, Any]) -> None:
        download_id = str(snapshot.get("download_id", "")).strip()
        model = str(snapshot.get("model", "Unknown model")).strip() or "Unknown model"
        if download_id and any(str(item.get("download_id", "")).strip() == download_id for item in self._download_history):
            return
        entry = {
            "download_id": download_id,
            "model": model,
            "completed_at": time.strftime("%H:%M:%S"),
            "note": "Ready to load from the Installed drawer.",
        }
        self._download_history = [entry, *self._download_history][:8]

    def _on_settings_sidebar_select(self, section_key: str) -> None:
        self._settings_sidebar_section = str(section_key or "").strip() or "appearance"
        labels = {
            "appearance": "Appearance",
            "runtime": "Runtime",
            "profiles": "Profiles",
            "workspace": "Workspace",
            "assistant": "Assistant",
            "downloads": "Downloads",
            "integrations": "Integrations",
            "privacy": "Privacy",
            "shortcuts": "Shortcuts",
            "advanced": "Advanced",
        }
        label = labels.get(str(section_key or "").strip(), "Settings")
        self._toolbar_status.patch(text=f"Settings section: {label}", color=self._MUTED)
        self._request_ui_refresh()

    def _on_models_sidebar_select(self, model_name: str) -> None:
        target = str(model_name or "").strip()
        if not target:
            return
        self._active_view = "models"
        self._open_model_detail(target)
        self._sync_models_sidebar()
        self._apply_active_view()

    def _on_astrea_mode_change(self, mode: str) -> None:
        self.astrea_page._set_mode(mode, emit=False)
        self.astrea_sidebar._set_mode(mode, emit=False)
        self._request_ui_refresh()

    def _on_astrea_refresh(self) -> None:
        self.astrea_service.refresh()

    def _on_astrea_generate(self, config: dict[str, Any]) -> None:
        try:
            snapshot = self.astrea_service.start_generation(config)
            self.astrea_page.set_snapshot(snapshot)
            self._sync_astrea_sidebar()
            self._toolbar_status.patch(text="Astrea generation started", color=self._MUTED)
        except Exception as exc:
            self._toolbar_status.patch(text=f"Astrea generate failed: {exc}", color="#B91C1C")
        self._request_ui_refresh()

    def _on_astrea_train(self, config: dict[str, Any]) -> None:
        try:
            snapshot = self.astrea_service.start_training(config)
            self.astrea_page.set_snapshot(snapshot)
            self._sync_astrea_sidebar()
            self._toolbar_status.patch(text="Astrea training started", color=self._MUTED)
        except Exception as exc:
            self._toolbar_status.patch(text=f"Astrea training failed: {exc}", color="#B91C1C")
        self._request_ui_refresh()

    def _on_astrea_caption(self, config: dict[str, Any]) -> None:
        try:
            snapshot = self.astrea_service.start_captioning(config)
            self.astrea_page.set_snapshot(snapshot)
            self._sync_astrea_sidebar()
            self._toolbar_status.patch(text="Astrea captioning started", color=self._MUTED)
        except Exception as exc:
            self._toolbar_status.patch(text=f"Astrea captioning failed: {exc}", color="#B91C1C")
        self._request_ui_refresh()

    def _on_astrea_build_dataset(self, config: dict[str, Any]) -> None:
        try:
            snapshot = self.astrea_service.build_dataset_config(config)
            self.astrea_page.set_snapshot(snapshot)
            self._sync_astrea_sidebar()
            self._toolbar_status.patch(text="Astrea dataset config generated", color=self._MUTED)
        except Exception as exc:
            self._toolbar_status.patch(text=f"Astrea dataset config failed: {exc}", color="#B91C1C")
        self._request_ui_refresh()

    def _on_astrea_cancel(self) -> None:
        snapshot = self.astrea_service.cancel_current_job()
        self.astrea_page.set_snapshot(snapshot)
        self._sync_astrea_sidebar()
        self._toolbar_status.patch(text="Astrea job cancelled", color=self._MUTED)
        self._request_ui_refresh()

    def _on_astrea_service_update(self, snapshot: dict[str, Any]) -> None:
        def _apply() -> None:
            self.astrea_page.set_snapshot(snapshot)
            self._sync_astrea_sidebar()
            self._request_ui_refresh()

        self._run_on_ui_thread(_apply)

    def _on_explorer_refresh(self) -> None:
        self._sync_explorer_sidebar()
        self._request_ui_refresh()

    def _on_explorer_file_select(self, file_path: str) -> None:
        target = str(file_path or "").strip()
        if not target:
            return
        self._ide_open_file = target
        self.ide_page.open_file(target)
        self._active_view = "ide"
        self._sync_explorer_sidebar()
        self._apply_active_view()
        self._request_ui_refresh()

    def _open_initial_ide_file(self) -> None:
        candidates = [
            self.paths.root / "README.md",
            self.paths.root / "main.py",
            self.paths.root / "requirements.txt",
        ]
        chosen: Path | None = None
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                chosen = candidate
                break
        if chosen is None:
            try:
                chosen = next(path for path in self.paths.root.rglob("*.py") if "env" not in path.parts and "__pycache__" not in path.parts)
            except StopIteration:
                chosen = None
        self.ide_page.set_workspace_root(self.paths.root)
        if chosen is None:
            self._sync_explorer_sidebar()
            return
        self._ide_open_file = str(chosen.resolve())
        self.ide_page.open_file(chosen)
        self._sync_explorer_sidebar()

    def _schedule_ide_state_sync(self, delay_seconds: float = 0.9) -> None:
        self._schedule_ui_callback(delay_seconds, self._poll_ide_state)

    def _poll_ide_state(self) -> None:
        if self._ui_loop is None or self._ide_state_poll_inflight:
            self._schedule_ide_state_sync(1.2)
            return
        self._ide_state_poll_inflight = True

        async def _capture() -> None:
            try:
                snapshot = await self.ide_page.capture_editor_state_async()
            except Exception:
                logger.exception("Failed capturing IDE editor state")
                snapshot = None

            def _apply() -> None:
                self._ide_state_poll_inflight = False
                try:
                    if isinstance(snapshot, dict):
                        previous_serial = self.ide_page.next_save_serial()
                        save_serial = int(snapshot.get("saveSerial", 0) or 0)
                        self.ide_page.apply_runtime_state(snapshot)
                        if save_serial > previous_serial:
                            self._on_ide_save_requested()
                finally:
                    self._schedule_ide_state_sync(0.9 if self._active_view == "ide" else 1.6)

            self._run_on_ui_thread(_apply)

        try:
            asyncio.create_task(_capture())
        except Exception:
            self._ide_state_poll_inflight = False
            self._schedule_ide_state_sync(1.6)

    def _on_ide_save_requested(self) -> None:
        target = str(self.ide_page.current_file_path() or self._ide_open_file).strip()
        if not target:
            self.ide_page.set_status("No file selected to save.", error=True)
            self._request_ui_refresh()
            return
        if self._ui_loop is None:
            self.ide_page.set_status("Editor runtime unavailable.", error=True)
            self._request_ui_refresh()
            return

        async def _save() -> None:
            snapshot = await self.ide_page.capture_editor_state_async()
            text = ""
            if isinstance(snapshot, dict):
                text = str(snapshot.get("text", ""))
            file_path = Path(target)
            try:
                file_path.write_text(text, encoding="utf-8")
            except Exception as exc:
                self._run_on_ui_thread(lambda: self.ide_page.set_status(f"Save failed: {exc}", error=True))
                self._run_on_ui_thread(self._request_ui_refresh)
                return

            def _apply() -> None:
                self._ide_open_file = str(file_path.resolve())
                self.ide_page.mark_saved(text)
                self._sync_explorer_sidebar()
                self._request_ui_refresh()

            self._run_on_ui_thread(_apply)

        try:
            asyncio.create_task(_save())
        except Exception:
            self.ide_page.set_status("Unable to start save task.", error=True)
            self._request_ui_refresh()

    def _apply_theme(self, theme: str) -> None:
        selected = str(theme or "system").strip().lower()
        if selected not in {"light", "dark", "system"}:
            selected = "system"
        is_dark = selected != "light"
        self._theme_mode = "dark" if is_dark else "light"
        self._apply_accent(self._accent_color, persist=False)
        self.page.bgcolor = self._palette["bg"]
        self._toolbar_status.patch(
            text=f"Theme: {selected}",
            color="#D1D5DB" if is_dark else self._MUTED,
        )

    def _on_theme_change(self, value=None, event=None) -> None:
        _ = event
        selected = str(value or "").strip() or self._read_theme_value()
        theme = self.settings_page.apply_theme_change(selected)
        self._apply_theme(theme)
        self._request_ui_refresh()

    def _apply_accent(self, color: str, *, persist: bool = True) -> None:
        accent = str(color or "").strip() or self._ACCENT
        self._accent_color = accent
        if persist:
            self.settings_page.apply_accent_change(accent)

        self._palette = build_palette(accent, dark=self._theme_mode != "light")
        self._ACCENT = self._palette["accent"]
        self._ON_ACCENT = self._palette["on_accent"]
        self._BG = self._palette["bg"]
        self._SURFACE = self._palette["surface"]
        self._SURFACE_ALT = self._palette["surface_alt"]
        self._BORDER = self._palette["border"]
        self._TEXT = self._palette["text"]
        self._MUTED = self._palette["muted"]
        self._refresh_stylesheet()
        self.page.bgcolor = self._BG

        self._llm_status.patch(color=self._MUTED)
        self._llm_model_summary.patch(color=self._MUTED)
        self._llm_model_count.patch(color=self._MUTED)
        self._toolbar_status.patch(color=self._MUTED)
        self._accent_chip.patch(value=self._ACCENT, border_color=self._BORDER)
        self._llm_drawer.patch(scrim_color=self._palette["overlay_scrim"])
        self._workspace_layer.patch(
            style=self._build_workspace_style(),
        )
        self.chat_page.set_palette(self._palette, session=self.page.session)
        self.ide_page.set_palette(self._palette)
        self.models_page.set_palette(self._palette)
        self.downloads_page.set_palette(self._palette)
        self.settings_page.set_palette(self._palette)
        self.astrea_page.set_palette(self._palette)
        self.conversations.set_palette(self._palette)
        self.explorer_sidebar.set_palette(self._palette)
        self.settings_sidebar.set_palette(self._palette)
        self.models_sidebar.set_palette(self._palette)
        self.downloads_sidebar.set_palette(self._palette)
        self.astrea_sidebar.set_palette(self._palette)
        if self.settings_page.use_translucent_panels() and self._background_image_path:
            self.chat_page.set_glass_mode(True)
            self.ide_page.set_glass_mode(True)
            self.models_page.set_glass_mode(True)
            self.downloads_page.set_glass_mode(True)
            self.settings_page.set_glass_mode(True)
            self.astrea_page.set_glass_mode(True)
            self.conversations.set_glass_mode(True)
            self.explorer_sidebar.set_glass_mode(True)
            self.settings_sidebar.set_glass_mode(True)
            self.models_sidebar.set_glass_mode(True)
            self.downloads_sidebar.set_glass_mode(True)
            self.astrea_sidebar.set_glass_mode(True)
            self._set_shell_glass_mode(True)
        self._apply_active_view()

    def _on_accent_change(self, value=None, event=None) -> None:
        chosen = ""
        if isinstance(value, str):
            chosen = value.strip()
        elif isinstance(value, dict):
            candidate = value.get("value", value.get("hex", value.get("color")))
            if candidate is not None:
                chosen = str(candidate).strip()
        elif value is not None:
            chosen = str(value).strip()
        if not chosen and isinstance(event, dict):
            payload = event.get("payload")
            if isinstance(payload, dict):
                candidate = payload.get("value", payload.get("hex", payload.get("color")))
                if candidate is not None:
                    chosen = str(candidate).strip()
        self._apply_accent(chosen or self._ACCENT, persist=True)
        self._close_accent_overlay()
        self.settings_page.set_appearance_status(f"Accent updated: {self._accent_color}")
        self._request_ui_refresh()

    def _open_accent_overlay(self, event=None) -> None:
        _ = event
        self.settings_page.get_accent_overlay().patch(open=True)
        self._request_ui_refresh()

    def _close_accent_overlay(self, event=None) -> None:
        _ = event
        self.settings_page.get_accent_overlay().patch(open=False)
        self._request_ui_refresh()

    def _ensure_asset_server(self) -> ui.AssetServer:
        if self._asset_server is not None:
            return self._asset_server
        self._asset_server = ui.AssetServer(host="127.0.0.1", port=0, base_path="/genesis-assets")
        self._asset_server.start()
        return self._asset_server

    def _resolve_background_asset(self, file_path: Path) -> Path:
        blur_amount = self.settings_page.get_background_blur()
        if blur_amount <= 0:
            return file_path

        resolved = file_path.resolve()
        fingerprint = hashlib.sha256(
            f"{resolved}|{resolved.stat().st_mtime_ns}|{blur_amount}".encode("utf-8")
        ).hexdigest()[:16]
        self._background_cache_dir.mkdir(parents=True, exist_ok=True)
        cached_path = self._background_cache_dir / f"{resolved.stem}-{fingerprint}.png"
        if cached_path.exists():
            return cached_path

        image = cv2.imread(str(resolved), cv2.IMREAD_UNCHANGED)
        if image is None:
            return file_path

        blurred = cv2.GaussianBlur(image, (0, 0), sigmaX=float(blur_amount), sigmaY=float(blur_amount))
        if not cv2.imwrite(str(cached_path), blurred):
            return file_path
        return cached_path

    def _set_shell_glass_mode(self, enabled: bool) -> None:
        self._refresh_stylesheet(force_glass=enabled)

    def _refresh_stylesheet(self, *, force_glass: bool | None = None) -> None:
        glass = force_glass
        if glass is None:
            glass = bool(self._background_image_path and self.settings_page.use_translucent_panels())
        self.page.set_stylesheet(build_stylesheet(self._palette, glass=bool(glass)))

    def _patch_background_opacity(self, opacity: int) -> None:
        if not self._background_asset_url:
            return
        self._workspace_layer.patch(
            image={
                "src": self._background_asset_url,
                "fit": "cover",
                "alignment": "center",
                "opacity": max(0.0, min(0.6, opacity / 100.0)),
            }
        )

    def _schedule_background_reapply(self, delay: float = 0.12) -> None:
        if not self._background_image_path:
            return
        self._background_refresh_token += 1
        token = self._background_refresh_token
        if self._background_refresh_timer is not None:
            self._background_refresh_timer.cancel()

        def _fire() -> None:
            if token != self._background_refresh_token:
                return

            def _apply() -> None:
                self._apply_background_image(self._background_image_path, persist=False)
                self._request_ui_refresh()

            self._run_on_ui_thread(_apply)

        self._background_refresh_timer = threading.Timer(delay, _fire)
        self._background_refresh_timer.daemon = True
        self._background_refresh_timer.start()

    def _apply_background_image(self, path: str, *, persist: bool) -> None:
        normalized = str(path or "").strip()
        if not normalized:
            self._workspace_layer.patch(image=None)
            self._background_asset_url = ""
            self._workspace_layer.patch(style=self._build_workspace_style())
            try:
                self.chat_page.set_glass_mode(False)
                self.ide_page.set_glass_mode(False)
                self.models_page.set_glass_mode(False)
                self.downloads_page.set_glass_mode(False)
                self.settings_page.set_glass_mode(False)
                self.astrea_page.set_glass_mode(False)
                self.conversations.set_glass_mode(False)
                self.explorer_sidebar.set_glass_mode(False)
                self.settings_sidebar.set_glass_mode(False)
                self.models_sidebar.set_glass_mode(False)
                self.downloads_sidebar.set_glass_mode(False)
                self.astrea_sidebar.set_glass_mode(False)
                self._set_shell_glass_mode(False)
            except Exception:
                pass
            self._background_image_path = ""
            if persist:
                self.settings_page.clear_background_path()
                self.settings_page.set_appearance_status("Background image cleared")
            return

        file_path = Path(normalized).expanduser()
        if not file_path.exists() or not file_path.is_file():
            self.settings_page.set_appearance_status("Background file not found", error=True)
            return

        try:
            server = self._ensure_asset_server()
            asset_path = self._resolve_background_asset(file_path)
            src_url = server.register_file(asset_path)
            self._background_asset_url = src_url
            self._workspace_layer.patch(
                image={
                    "src": src_url,
                    "fit": "cover",
                    "alignment": "center",
                    "opacity": max(0.0, min(0.6, self.settings_page.get_background_opacity() / 100.0)),
                }
            )
            glass_enabled = self.settings_page.use_translucent_panels()
            try:
                self.chat_page.set_glass_mode(glass_enabled)
                self.ide_page.set_glass_mode(glass_enabled)
                self.models_page.set_glass_mode(glass_enabled)
                self.downloads_page.set_glass_mode(glass_enabled)
                self.settings_page.set_glass_mode(glass_enabled)
                self.astrea_page.set_glass_mode(glass_enabled)
                self.conversations.set_glass_mode(glass_enabled)
                self.explorer_sidebar.set_glass_mode(glass_enabled)
                self.settings_sidebar.set_glass_mode(glass_enabled)
                self.models_sidebar.set_glass_mode(glass_enabled)
                self.downloads_sidebar.set_glass_mode(glass_enabled)
                self.astrea_sidebar.set_glass_mode(glass_enabled)
                self._set_shell_glass_mode(glass_enabled)
            except Exception:
                pass
            self._background_image_path = str(file_path.resolve())
            if persist:
                self.settings_page.set_background_path(self._background_image_path)
                self.settings_page.set_appearance_status("Background image applied")
        except Exception as exc:
            logger.exception("Failed applying background image")
            self.settings_page.set_appearance_status(f"Background apply failed: {exc}", error=True)

    def _extract_file_picker_path(self, event: Any) -> str:
        payload: dict[str, Any] = {}
        if isinstance(event, dict):
            maybe_payload = event.get("payload")
            if isinstance(maybe_payload, dict):
                payload = maybe_payload
            else:
                payload = event
        elif event is not None:
            maybe_payload = getattr(event, "payload", None)
            if isinstance(maybe_payload, dict):
                payload = maybe_payload

        def _from_item(item: Any) -> str:
            if isinstance(item, dict):
                value = item.get("path", item.get("value", ""))
                return str(value or "").strip()
            return str(item or "").strip()

        files = payload.get("files")
        if isinstance(files, list) and files:
            for item in files:
                candidate = _from_item(item)
                if candidate:
                    return candidate

        value = payload.get("value")
        if isinstance(value, list) and value:
            for item in value:
                candidate = _from_item(item)
                if candidate:
                    return candidate
        if isinstance(value, dict):
            return _from_item(value)
        if isinstance(value, str) and value.strip():
            return value.strip()

        data = payload.get("data")
        if isinstance(data, dict):
            return _from_item(data)
        return ""

    def _on_background_result(self, value=None, event=None) -> None:
        path = ""
        if value is not None and isinstance(value, str):
            path = value.strip()
        elif isinstance(value, dict):
            path = self._extract_file_picker_path(value)
        if not path:
            path = self._extract_file_picker_path(event)
        if not path:
            return
        try:
            self._apply_background_image(path, persist=True)
        except Exception as exc:
            logger.exception("Background upload failed")
            self.settings_page.set_appearance_status(f"Background upload failed: {exc}", error=True)
        self._request_ui_refresh()

    def _on_background_clear(self, event=None) -> None:
        _ = event
        self._apply_background_image("", persist=True)
        self._request_ui_refresh()

    def _on_background_opacity_change(self, value=None, event=None) -> None:
        _ = event
        opacity = self.settings_page.apply_background_opacity_change(value)
        if self._background_image_path:
            self._patch_background_opacity(opacity)
        self.settings_page.set_appearance_status(f"Background opacity updated: {opacity}%")
        self._request_ui_refresh()

    def _on_background_blur_change(self, value=None, event=None) -> None:
        _ = event
        blur = self.settings_page.apply_background_blur_change(value)
        if self._background_image_path:
            self._schedule_background_reapply()
        self.settings_page.set_appearance_status(f"Background blur updated: {blur}")
        self._request_ui_refresh()

    def _on_translucent_panels_change(self, value=None, event=None) -> None:
        _ = event
        enabled = self.settings_page.apply_translucent_panels_change(value)
        if self._background_image_path:
            self._apply_background_image(self._background_image_path, persist=False)
        else:
            self.chat_page.set_glass_mode(False)
            self.ide_page.set_glass_mode(False)
            self.models_page.set_glass_mode(False)
            self.downloads_page.set_glass_mode(False)
            self.settings_page.set_glass_mode(False)
            self.conversations.set_glass_mode(False)
            self.explorer_sidebar.set_glass_mode(False)
            self.settings_sidebar.set_glass_mode(False)
            self.models_sidebar.set_glass_mode(False)
            self.downloads_sidebar.set_glass_mode(False)
            self._set_shell_glass_mode(False)
        self.settings_page.set_appearance_status(
            "Translucent panels enabled" if enabled else "Translucent panels disabled"
        )
        self._request_ui_refresh()

    def _render_downloads_page(self) -> None:
        self.downloads_page.render(self._download_manager.list_downloads(), banner=self._downloads_banner)
        self._sync_downloads_sidebar()

    def _on_downloads_refresh(self) -> None:
        self._render_downloads_page()
        self._request_ui_refresh()

    def _on_download_pause(self, download_id: str) -> None:
        try:
            self._download_manager.pause_download(download_id)
        except Exception as exc:
            self.downloads_page.set_status(f"Pause failed: {exc}", error=True)
        self._render_downloads_page()
        self._request_ui_refresh()

    def _on_download_resume(self, download_id: str) -> None:
        try:
            self._download_manager.resume_download(download_id)
        except Exception as exc:
            self.downloads_page.set_status(f"Resume failed: {exc}", error=True)
        self._render_downloads_page()
        self._request_ui_refresh()

    def _on_models_refresh(self) -> None:
        self.models_page.set_status("Refreshing Ollama library...")
        self._request_ui_refresh()
        self._refresh_models_catalog(force=True)

    def _refresh_models_catalog(self, *, force: bool) -> None:
        if self._catalog_entries and not force:
            self._render_models_catalog()
            return
        threading.Thread(
            target=lambda: self._load_models_catalog(force=force),
            daemon=True,
            name="genesis-ollama-library-catalog",
        ).start()

    def _load_models_catalog(self, *, force: bool) -> None:
        try:
            entries = [item.to_dict() for item in self._ollama_library.list_catalog(force=force)]
        except Exception as exc:
            logger.exception("Failed to load Ollama library catalog")
            self._run_on_ui_thread(lambda: self.models_page.set_status(f"Library load failed: {exc}", error=True))
            self._request_ui_refresh()
            return

        def _apply() -> None:
            self._catalog_entries = entries
            self._catalog_page = 1
            self._render_models_catalog()
            self.models_page.set_status(f"Loaded {len(entries)} Ollama models", success=True)
            self._request_ui_refresh()

        self._run_on_ui_thread(_apply)

    def _render_models_catalog(self) -> None:
        total_count = len(self._catalog_entries)
        page_count = max(1, math.ceil(total_count / self._catalog_page_size)) if total_count else 1
        self._catalog_page = min(max(1, self._catalog_page), page_count)
        start = (self._catalog_page - 1) * self._catalog_page_size
        end = start + self._catalog_page_size
        page_items = self._catalog_entries[start:end]
        self.models_page.render_catalog(
            page_items,
            page=self._catalog_page,
            page_count=page_count,
            total_count=total_count,
            installed_models=set(self._available_models),
            active_model=self._active_model,
        )
        self._sync_models_sidebar()

    def _on_models_page_change(self, page: int) -> None:
        self._catalog_page = max(1, int(page))
        self._render_models_catalog()
        self._request_ui_refresh()

    def _open_model_detail(self, model_name: str) -> None:
        target = str(model_name or "").strip().lower()
        if not target:
            return
        self.models_page.set_status(f"Loading {target}...")
        self._request_ui_refresh()
        threading.Thread(
            target=lambda: self._load_model_detail(target, force=False),
            daemon=True,
            name=f"genesis-ollama-detail-{target}",
        ).start()

    def _load_model_detail(self, model_name: str, *, force: bool) -> None:
        try:
            detail = self._ollama_library.get_detail(model_name, force=force).to_dict()
        except Exception as exc:
            logger.exception("Failed to load Ollama model detail")
            self._run_on_ui_thread(lambda: self.models_page.set_status(f"Model detail failed: {exc}", error=True))
            self._request_ui_refresh()
            return

        def _apply() -> None:
            self._current_model_detail = detail
            default_target = str(detail.get("default_pull_target", detail.get("name", ""))).strip()
            if self._selected_pull_target not in detail.get("pull_targets", []):
                self._selected_pull_target = default_target
            self._render_current_model_detail()
            self.models_page.set_status(f"Loaded {model_name}", success=True)
            self._request_ui_refresh()

        self._run_on_ui_thread(_apply)

    def _render_current_model_detail(self) -> None:
        if not self._current_model_detail:
            return
        detail = self._current_model_detail
        targets = [str(item).strip() for item in detail.get("pull_targets", []) if str(item).strip()]
        selected_target = self._selected_pull_target.strip() or str(detail.get("default_pull_target", "")).strip()
        if selected_target not in targets and targets:
            selected_target = targets[0]
            self._selected_pull_target = selected_target
        self.models_page.show_detail(
            detail,
            selected_target=selected_target,
            installed_models=set(self._available_models),
            active_model=self._active_model,
            pull_in_progress=self._is_download_active(selected_target),
        )
        self._sync_models_sidebar()

    def _on_model_detail_back(self) -> None:
        self.models_page.show_catalog()
        self._render_models_catalog()
        self._request_ui_refresh()

    def _on_model_variant_change(self, value: str) -> None:
        self._selected_pull_target = str(value or "").strip()
        self._render_current_model_detail()
        self._request_ui_refresh()

    def _on_model_pull(self) -> None:
        detail = self._current_model_detail or {}
        target = self._selected_pull_target.strip() or str(detail.get("default_pull_target", "")).strip()
        if not target:
            self.models_page.set_status("Choose a model variant before pulling.", error=True)
            self._request_ui_refresh()
            return
        self.models_page.set_status(f"Starting pull for {target}...")
        self._downloads_banner = f"Starting download: {target}"
        self._active_view = "downloads"
        self._render_downloads_page()
        self._apply_active_view()
        self._request_ui_refresh()
        threading.Thread(
            target=lambda: self._start_model_download(target),
            daemon=True,
            name=f"genesis-ollama-pull-{target}",
        ).start()

    def _start_model_download(self, target: str) -> None:
        result = self._prepare_ollama_model_store(announce=False)
        if not result.ok:
            message = str(result.error or "Unable to reach Ollama service.").strip()
            self._run_on_ui_thread(lambda: self.models_page.set_status(f"Pull failed: {message}", error=True))
            self._request_ui_refresh()
            return

        try:
            snapshot = self._download_manager.start_download(
                model=target,
                base_url=str(result.base_url or self.settings.ollama_base_url).rstrip("/"),
            )
        except Exception as exc:
            logger.exception("Failed to queue Ollama pull")
            self._run_on_ui_thread(lambda: self.models_page.set_status(f"Pull failed: {exc}", error=True))
            self._request_ui_refresh()
            return

        def _apply() -> None:
            self._downloads_banner = f"Downloading {snapshot.get('model', target)}"
            self._render_downloads_page()
            self._render_current_model_detail()
            self._request_ui_refresh()

        self._run_on_ui_thread(_apply)

    def _is_download_active(self, model: str) -> bool:
        target = str(model or "").strip()
        if not target:
            return False
        for item in self._download_manager.list_downloads():
            if str(item.get("model", "")).strip() == target and not bool(item.get("done", False)):
                return True
        return False

    def _download_matches_current_detail(self, model: str) -> bool:
        if not self._current_model_detail:
            return False
        detail_name = str(self._current_model_detail.get("name", "")).strip()
        target = str(model or "").strip()
        return bool(detail_name and target and (target == detail_name or target.startswith(f"{detail_name}:")))

    def _on_download_update(self, snapshot: dict[str, Any]) -> None:
        def _apply() -> None:
            model = str(snapshot.get("model", "model")).strip() or "model"
            error_value = snapshot.get("error")
            error = "" if error_value in {None, "None"} else str(error_value).strip()
            done = bool(snapshot.get("done", False))
            paused = bool(snapshot.get("paused", False))
            progress = snapshot.get("progress_percent")

            if done and not error:
                banner = f"Download complete: {model}"
                self._record_completed_download(snapshot)
                self.models_page.set_status(banner, success=True)
                self.downloads_page.set_status(banner, success=True)
                self._toolbar_status.patch(text=banner, color=self._SUCCESS)
                if model and model not in self._available_models:
                    self._available_models = sorted(set([*self._available_models, model]))
                    self._selected_model = model
                    self._update_model_select_options(self._available_models)
                self._send_runtime("runtime.models.list", {}, intent="runtime.models.list")
                self._send_runtime("runtime.health", {}, intent="runtime.health")
            elif paused:
                banner = f"Download paused: {model}"
                self.models_page.set_status(banner)
                self.downloads_page.set_status(banner)
                self._toolbar_status.patch(text=banner, color=self._MUTED)
            elif error:
                banner = f"Download failed: {model}"
                self.models_page.set_status(banner, error=True)
                self.downloads_page.set_status(banner, error=True)
                self._toolbar_status.patch(text=banner, color=self._ERROR)
            else:
                suffix = f" {progress}%" if isinstance(progress, int) else ""
                banner = f"Downloading {model}{suffix}"
                self.models_page.set_status(banner)
                self.downloads_page.set_status(banner)
                self._toolbar_status.patch(text=banner, color=self._MUTED)

            self._downloads_banner = banner
            self._render_downloads_page()
            if self._download_matches_current_detail(model):
                self._render_current_model_detail()
            self._request_ui_refresh()

        self._run_on_ui_thread(_apply)

    def _toggle_llm_drawer(self, event=None) -> None:
        _ = event
        self._set_llm_drawer_open(not self._llm_drawer_open)
        if self._llm_drawer_open:
            self._send_runtime("runtime.models.list", {}, intent="runtime.models.list")
        self._request_ui_refresh()

    def _on_llm_drawer_closed(self, event=None) -> None:
        _ = event
        self._set_llm_drawer_open(False)
        self._request_ui_refresh()

    def _on_llm_close_button(self, event=None) -> None:
        _ = event
        self._set_llm_drawer_open(False)
        self._request_ui_refresh()

    def _set_llm_drawer_open(self, open_value: bool) -> None:
        self._llm_drawer_open = bool(open_value)
        self._llm_drawer.patch(open=self._llm_drawer_open)

    def _on_llm_model_change(self, value=None, event=None) -> None:
        selected = ""
        if isinstance(value, str):
            selected = value.strip()
        elif isinstance(value, dict):
            candidate = value.get("value", value.get("label", value.get("text")))
            if candidate is not None:
                selected = str(candidate).strip()
        elif value is not None:
            selected = str(value).strip()
        if not selected and isinstance(event, dict):
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else event
            candidate = payload.get("value", payload.get("label", payload.get("text")))
            if candidate is not None:
                selected = str(candidate).strip()
        if not selected:
            selected = self._read_control_value(self._llm_model_select, self._selected_model)
        self._selected_model = selected or self._selected_model

    def _on_llm_refresh(self, event=None) -> None:
        _ = event
        self._llm_status.patch(text="Refreshing models...", color=self._MUTED)
        self._send_runtime("runtime.models.list", {}, intent="runtime.models.list")
        self._request_ui_refresh()

    def _on_llm_use_model(self, event=None) -> None:
        _ = event
        model = self._selected_model.strip()
        if not model:
            self._llm_status.patch(text="Choose a model first", color="#B91C1C")
            self._request_ui_refresh()
            return
        self._llm_status.patch(text=f"Setting model: {model}", color=self._MUTED)
        self._send_runtime("runtime.model.set", {"model": model}, intent="runtime.model.set")
        self._request_ui_refresh()

    def _on_llm_load_model(self, event=None) -> None:
        _ = event
        model = self._selected_model.strip()
        if not model:
            self._llm_status.patch(text="Choose a model first", color="#B91C1C")
            self._request_ui_refresh()
            return
        self._llm_status.patch(text=f"Loading {model}...", color=self._MUTED)
        self._send_runtime(
            "runtime.model.load",
            {"model": model, "keep_alive": "30m"},
            intent="runtime.model.load",
        )
        self._request_ui_refresh()

    def _on_llm_unload_model(self, event=None) -> None:
        _ = event
        model = self._selected_model.strip() or self._active_model
        if not model:
            self._llm_status.patch(text="No active model to unload", color="#B91C1C")
            self._request_ui_refresh()
            return
        self._llm_status.patch(text=f"Unloading {model}...", color=self._MUTED)
        self._send_runtime(
            "runtime.model.unload",
            {"model": model},
            intent="runtime.model.unload",
        )
        self._request_ui_refresh()

    def _update_model_select_options(self, models: list[str]) -> None:
        options = [{"label": name, "value": name} for name in models] or [
            {"label": self._active_model, "value": self._active_model}
        ]
        selected = self._selected_model if self._selected_model in models else self._active_model
        if not selected:
            selected = options[0]["value"]
        self._selected_model = selected
        self._llm_model_select.patch(options=options, value=selected)
        count = len(models)
        self._llm_model_count.patch(text=f"{count} installed" if count != 1 else "1 installed")
        if count:
            self._llm_model_summary.patch(text="Choose any pulled model, then load it or make it active.")
        else:
            self._llm_model_summary.patch(text="No pulled models detected yet. Pull one from the Models page first.")
        self._sync_models_sidebar()

    def _persist_active_model(self, model: str) -> None:
        target = str(model or "").strip()
        if not target:
            return
        runtime_config = self.settings_page.get_runtime_config(session=self.page.session)
        runtime_config["model"] = target
        self.settings_page.apply_runtime_change(runtime_config)
        self.settings = load_runtime_settings(self.paths.settings_file)
        self.bridge._settings = self.settings

    def _on_runtime_save(self, event=None) -> None:
        _ = event
        config = self.settings_page.get_runtime_config(session=self.page.session)
        saved = self.settings_page.apply_runtime_change(config)
        self.settings = load_runtime_settings(self.paths.settings_file)
        self.bridge._settings = self.settings
        self._active_model = str(saved.get("model", self._active_model)).strip() or self._active_model
        self._selected_model = self._active_model
        self._sync_ollama_bootstrap_from_settings()
        self.settings_page.set_runtime_status("Runtime settings saved. Applying Ollama service bootstrap...")
        self._llm_status.patch(text="Runtime settings saved", color=self._MUTED)
        threading.Thread(
            target=lambda: self._prepare_ollama_model_store(announce=True),
            daemon=True,
        ).start()
        self._send_runtime(
            "runtime.base_url.set",
            {"ollama_base_url": str(saved.get("ollama_base_url", self.settings.ollama_base_url))},
            intent="runtime.base_url.set",
        )
        self._send_runtime("runtime.model.set", {"model": self._active_model}, intent="runtime.model.set")
        self._send_runtime("runtime.models.list", {}, intent="runtime.models.list")
        self._request_ui_refresh()

    def _on_runtime_health_request(self, event=None) -> None:
        _ = event
        self.settings_page.set_runtime_status("Requesting runtime health...")
        self._send_runtime("runtime.health", {}, intent="runtime.health")
        self._request_ui_refresh()

    def _on_send(self, event=None) -> None:
        text = self._extract_event_text(event).strip()
        if not text:
            text = self.chat_page.get_composer_text()
        if not text:
            return

        self.chat_page.clear_composer()
        self.chat_page.add_user_message(text, self.page.session)

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
        self._send_runtime("session.list", {}, intent="session.list.refresh")

    def _open_session(self, session_id: str) -> None:
        if self.current_session_id == session_id:
            return

        self._cache_active_session_state()
        self.current_session_id = session_id
        self.conversations.set_active(session_id)
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
            self.models_page.set_status(f"Runtime error: {msg}", error=True)
            self.downloads_page.set_status(f"Runtime error: {msg}", error=True)
            self.settings_page.set_runtime_status(f"Runtime error: {msg}")
            self._llm_status.patch(text=f"Runtime error: {msg}", color="#B91C1C")
            self._request_ui_refresh()
            return

        method = message.get("method")
        params = message.get("params", {})

        if method == "session.updated":
            self._handle_session_updated(params)
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
            self._request_ui_refresh()
            now = time.monotonic()
            if now - self._last_delta_refresh >= 0.12:
                self._last_delta_refresh = now
                self._cache_active_session_state()
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
            if model:
                self._active_model = model
            self.chat_page.set_runtime_label(f"Runtime: {backend} ({model})" if model else f"Runtime: {backend}")
            self.settings_page.set_runtime_status(f"Runtime info loaded ({backend})")
            self._toolbar_status.patch(text=f"{backend} ready", color=self._MUTED)
            if self._catalog_entries:
                self._render_models_catalog()
            if self._current_model_detail:
                self._render_current_model_detail()
            self._sync_models_sidebar()
            self._request_ui_refresh()
            return

        if request_intent == "runtime.health":
            self.settings_page.set_runtime_health(result)
            self._request_ui_refresh()
            return

        if request_intent == "runtime.models.list":
            models_raw = result.get("models", [])
            parsed_models: list[str] = []
            if isinstance(models_raw, list):
                for item in models_raw:
                    if isinstance(item, dict):
                        name = str(item.get("name", "")).strip()
                        if name:
                            parsed_models.append(name)
                    elif isinstance(item, str):
                        name = item.strip()
                        if name:
                            parsed_models.append(name)
            parsed_models = sorted(set(parsed_models))
            self._available_models = parsed_models
            if self._active_model and self._active_model not in self._available_models:
                self._available_models.insert(0, self._active_model)
            if self._selected_model not in self._available_models and self._available_models:
                self._selected_model = self._available_models[0]
            self._update_model_select_options(self._available_models)
            count = len(self._available_models)
            self._llm_status.patch(text=f"{count} model(s) available", color=self._MUTED)
            if self._catalog_entries:
                self._render_models_catalog()
            if self._current_model_detail:
                self._render_current_model_detail()
            self._sync_models_sidebar()
            self._request_ui_refresh()
            return

        if request_intent == "runtime.base_url.set":
            ok = bool(result.get("ok", False))
            if ok:
                base_url = str(result.get("ollama_base_url", "")).strip() or self.settings.ollama_base_url
                self._llm_status.patch(text=f"Ollama endpoint: {base_url}", color=self._MUTED)
                self._send_runtime("runtime.info", {}, intent="runtime.info")
                self._send_runtime("runtime.health", {}, intent="runtime.health")
                self._send_runtime("runtime.models.list", {}, intent="runtime.models.list")
            else:
                error = str(result.get("error", "Failed setting Ollama endpoint")).strip()
                self._llm_status.patch(text=error, color="#B91C1C")
            self._request_ui_refresh()
            return

        if request_intent == "runtime.model.set":
            ok = bool(result.get("ok", False))
            model = str(result.get("model", "")).strip()
            if ok and model:
                self._active_model = model
                self._selected_model = model
                self._persist_active_model(model)
                self._update_model_select_options(self._available_models)
                self._llm_status.patch(text=f"Active model: {model}", color=self._MUTED)
                self.chat_page.set_runtime_label(f"Runtime: Ollama ({model})")
                self._send_runtime("runtime.info", {}, intent="runtime.info")
                self._send_runtime("runtime.health", {}, intent="runtime.health")
                self._send_runtime("runtime.models.list", {}, intent="runtime.models.list")
                if self._current_model_detail:
                    self._render_current_model_detail()
            else:
                error = str(result.get("error", "Failed setting model")).strip()
                self._llm_status.patch(text=error, color="#B91C1C")
            self._request_ui_refresh()
            return

        if request_intent == "runtime.model.load":
            ok = bool(result.get("ok", False))
            model = str(result.get("model", self._selected_model)).strip()
            if ok:
                warning = str(result.get("warning", "")).strip()
                self._active_model = model or self._active_model
                if self._active_model and self._active_model not in self._available_models:
                    self._available_models = sorted(set([*self._available_models, self._active_model]))
                self._selected_model = self._active_model
                self._persist_active_model(self._active_model)
                self._update_model_select_options(self._available_models)
                message = f"Loaded {self._active_model}" if not warning else f"Loaded {self._active_model} locally"
                self._llm_status.patch(text=message, color="#047857")
                self.chat_page.set_runtime_label(f"Runtime: Ollama ({self._active_model})")
                self._send_runtime("runtime.health", {}, intent="runtime.health")
                if self._current_model_detail:
                    self._render_current_model_detail()
            else:
                error = str(result.get("error", "Load failed")).strip()
                self._llm_status.patch(text=f"Load failed: {error}", color="#B91C1C")
            self._send_runtime("runtime.models.list", {}, intent="runtime.models.list")
            self._request_ui_refresh()
            return

        if request_intent == "runtime.model.unload":
            ok = bool(result.get("ok", False))
            model = str(result.get("model", self._selected_model)).strip()
            if ok:
                warning = str(result.get("warning", "")).strip()
                message = f"Unloaded {model}" if not warning else f"Unloaded {model} locally"
                self._llm_status.patch(text=message, color=self._MUTED)
            else:
                error = str(result.get("error", "Unload failed")).strip()
                self._llm_status.patch(text=f"Unload failed: {error}", color="#B91C1C")
            self._send_runtime("runtime.health", {}, intent="runtime.health")
            if self._current_model_detail:
                self._render_current_model_detail()
            self._request_ui_refresh()
            return

        if "sessions" in result:
            self._sessions = result.get("sessions", [])
            should_open_current = False
            if not self.current_session_id and self._sessions:
                self.current_session_id = self._sessions[0].get("id")
                should_open_current = bool(self.current_session_id)
            self.conversations.set_sessions(self._sessions, self.current_session_id)
            self._request_ui_refresh()
            if not self._sessions:
                self._on_new_chat()
            elif (
                self.current_session_id
                and request_intent == "session.list.bootstrap"
                and not self._session_view_cache.get(self.current_session_id)
            ) or should_open_current:
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
            self.conversations.set_sessions(self._sessions, session_id)
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

    def _handle_session_updated(self, params: dict[str, Any]) -> None:
        session_id = str(params.get("session_id", "")).strip()
        action = str(params.get("action", "")).strip().lower()
        title = str(params.get("title", "")).strip()

        if not session_id:
            self._send_runtime("session.list", {}, intent="session.list.refresh")
            return

        if action == "message":
            self._cache_active_session_state()

        if title:
            if session_id == self.current_session_id:
                self.chat_page.set_title(title)
            cached = self._session_view_cache.get(session_id)
            if cached is not None:
                cached["title"] = title

        updated = self._refresh_session_summary(session_id, title=title or None)
        if updated:
            self.conversations.set_sessions(self._sessions, self.current_session_id)
            self._request_ui_refresh()

        if action == "created" or not updated:
            self._send_runtime("session.list", {}, intent="session.list.refresh")

    def _refresh_session_summary(self, session_id: str, *, title: str | None = None) -> bool:
        if not session_id:
            return False

        cached = self._session_view_cache.get(session_id)
        if cached is None and session_id == self.current_session_id:
            self._cache_active_session_state()
            cached = self._session_view_cache.get(session_id)

        updated = False
        for session in self._sessions:
            if str(session.get("id", "")).strip() != session_id:
                continue
            if title:
                session["title"] = title
                updated = True
            if cached is not None:
                messages = cached.get("messages", []) if isinstance(cached, dict) else []
                session["message_count"] = str(len(messages))
                session["preview"] = self._session_preview_from_snapshot(messages)
                cached_title = str(cached.get("title", "")).strip() if isinstance(cached, dict) else ""
                if cached_title:
                    session["title"] = cached_title
                updated = True
            if updated:
                self._sessions = [session, *[item for item in self._sessions if item is not session]]
            break
        return updated

    @staticmethod
    def _session_preview_from_snapshot(messages: list[dict[str, Any]] | None) -> str:
        if not messages:
            return "New conversation"
        last = messages[-1] if isinstance(messages[-1], dict) else {}
        text = str(last.get("text", "")).strip()
        compact = " ".join(text.split())
        return compact[:88] if compact else "New conversation"

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

    def _schedule_ui_callback(self, delay_seconds: float, callback) -> None:
        delay = max(0.0, float(delay_seconds))
        if self._ui_loop is not None:
            try:
                self._ui_loop.call_later(delay, self._run_on_ui_thread, callback)
                return
            except Exception:
                pass
        timer = threading.Timer(delay, lambda: self._run_on_ui_thread(callback))
        timer.daemon = True
        timer.start()

    def _run_on_ui_thread(self, callback) -> None:
        if self._ui_loop is None:
            try:
                callback()
            except Exception:
                logger.exception("UI callback failed")
            return
        try:
            self._ui_loop.call_soon_threadsafe(callback)
        except Exception:
            try:
                callback()
            except Exception:
                logger.exception("UI callback failed")

    def _sync_ollama_bootstrap_from_settings(self) -> None:
        self._ollama_bootstrap.update_config(
            ollama_base_url=self.settings.ollama_base_url,
            model=self._active_model,
            models_dir=self.settings.ollama_models_dir,
            auto_pull=False,
            request_timeout=self.settings.request_timeout,
        )

    def _prepare_ollama_model_store(self, *, announce: bool = False):
        self._sync_ollama_bootstrap_from_settings()
        result = self._ollama_bootstrap.prepare()
        resolved_base = str(result.base_url or "").strip().rstrip("/")
        current_base = str(self.settings.ollama_base_url or "").strip().rstrip("/")
        if resolved_base and resolved_base != current_base:
            updated_runtime = {
                "model": self._active_model,
                "ollama_base_url": resolved_base,
                "request_timeout": self.settings.request_timeout,
                "ollama_models_dir": self.settings.ollama_models_dir,
                "ollama_auto_pull": False,
                "preferred_shell": self.settings.preferred_shell,
            }
            self.settings_page.apply_runtime_change(updated_runtime)
            self.settings = load_runtime_settings(self.paths.settings_file)
            self.bridge._settings = self.settings
            self._send_runtime(
                "runtime.base_url.set",
                {"ollama_base_url": resolved_base},
                intent="runtime.base_url.set",
            )
        if result.ok:
            logger.info(
                "Ollama bootstrap ready (base_url=%s, models_dir=%s, model=%s, pulled=%s)",
                result.base_url,
                result.models_dir,
                result.model,
                result.model_pulled,
            )
        else:
            logger.warning(
                "Ollama bootstrap failed (base_url=%s, models_dir=%s, model=%s, error=%s)",
                result.base_url,
                result.models_dir,
                result.model,
                result.error,
            )
        if announce:
            if result.ok:
                self.settings_page.set_runtime_status(f"Ollama service ready: {result.base_url}")
                self._toolbar_status.patch(text="Ollama service ready", color=self._MUTED)
            else:
                detail = f": {result.error}" if result.error else ""
                self.settings_page.set_runtime_status(f"Ollama service bootstrap failed{detail}")
                self._toolbar_status.patch(text="Ollama service failed", color="#B91C1C")
            self._request_ui_refresh()
        return result

    def _read_control_value(self, control: Any, fallback: str) -> str:
        session = self.page.session if self.page is not None else None
        if session is not None:
            try:
                value = session.get_value(control, prop="value")
                if value is not None:
                    return str(value)
            except Exception:
                pass
        try:
            return str(control.to_dict().get("props", {}).get("value", fallback))
        except Exception:
            return str(fallback)

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
