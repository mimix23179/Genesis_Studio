from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import butterflyui as ui

from app.ui.theme import text_on


class SettingsPage:
    _SURFACE = "#FFFFFF"
    _SURFACE_ALT = "#F8FAFC"
    _BORDER = "#D1D5DB"
    _TEXT = "#0F172A"
    _MUTED = "#64748B"
    _ACCENT = "#10A37F"
    _ERROR = "#B91C1C"
    _OK = "#047857"

    def __init__(self, settings_file: Path) -> None:
        self.settings_file = settings_file
        self._state: dict[str, Any] = self._load_settings()
        self._glass_mode = False
        self._header_surface: ui.Surface | None = None
        self._appearance_surface: ui.Surface | None = None
        self._accent_surface: ui.Surface | None = None
        self._accent_overlay_surface: ui.Surface | None = None
        self._runtime_surface: ui.Surface | None = None
        self._accent_buttons: dict[str, ui.Button] = {}
        self._accent_close_button: ui.Button | None = None

        appearance = self._state.get("appearance", {}) if isinstance(self._state.get("appearance"), dict) else {}
        runtime = self._state.get("runtime", {}) if isinstance(self._state.get("runtime"), dict) else {}

        theme_value = str(appearance.get("theme", "system")).strip() or "system"
        accent_value = str(appearance.get("accent_color", self._ACCENT)).strip() or self._ACCENT
        background_path = str(appearance.get("background_image", "")).strip()
        background_opacity_raw = appearance.get("background_opacity", 24)
        try:
            background_opacity = int(float(background_opacity_raw))
        except Exception:
            background_opacity = 24
        background_opacity = max(0, min(60, background_opacity))
        background_blur_raw = appearance.get("background_blur", 8)
        try:
            background_blur = int(float(background_blur_raw))
        except Exception:
            background_blur = 8
        background_blur = max(0, min(24, background_blur))
        translucent_panels = bool(appearance.get("translucent_panels", True))

        self.title = ui.Text("Settings", font_size=24, font_weight="700", color=self._TEXT)
        self.subtitle = ui.Text("Appearance and Runtime", font_size=12, color=self._MUTED)

        self.theme_select = ui.Select(
            label="Theme",
            class_name="gs-input",
            value=theme_value,
            options=[
                {"label": "Light", "value": "light"},
                {"label": "Dark", "value": "dark"},
                {"label": "System", "value": "system"},
            ],
            events=["change"],
            width=220,
        )
        self.accent_picker = ui.ColorPicker(
            value=accent_value,
            events=["change"],
            emit_on_change=True,
            show_input=True,
            show_actions=False,
            show_presets=True,
            preview_height=148,
            presets=[
                "#10A37F", "#4F46E5", "#0EA5E9", "#F59E0B", "#EC4899", "#16A34A",
                "#5C10A3", "#FF7B00", "#E90E62", "#F5D20B", "#5BE2C0", "#69E1FF",
                "#8D0000", "#FF5050", "#9FE1FF", "#75482A", "#FF7BBD", "#34003B",
                "#643170", "#24215A", "#437D97", "#725014", "#E04D59", "#98C276",
                "#FF8800", "#E57846", "#0075AC", "#292469", "#4D2680", "#4B00A0",
                "#A0E426", "#FF6F91", "#D7263D", "#F46036", "#2E294E", "#1B998B",
                "#FF1654", "#FBB13C", "#FA7921", "#3A86FF", "#8338EC", "#FF006E",
            ],
            width=340,
        )
        self.accent_open_button = ui.Button(
            text="Choose Accent",
            class_name="gs-button gs-outline",
            variant="outlined",
            events=["click"],
            radius=10,
            border_width=1,
        )
        self.accent_preview = ui.Color(
            value=accent_value,
            show_label=False,
            show_hex=False,
            width=72,
            height=72,
            radius=18,
            border_color="#FFFFFF66",
            border_width=1,
            auto_contrast=True,
        )
        self.accent_value_text = ui.Text(accent_value, font_size=12, font_weight="700", color=self._TEXT)
        self.accent_hint = ui.Text(
            "Open the overlay, click any tone, and Genesis updates instantly.",
            font_size=11,
            color=self._MUTED,
        )
        self._accent_presets = [
            "#10A37F", "#14B8A6", "#0EA5E9", "#3B82F6", "#4F46E5", "#6366F1", "#7C3AED", "#8B5CF6",
            "#A855F7", "#D946EF", "#EC4899", "#F43F5E", "#EF4444", "#F97316", "#F59E0B", "#EAB308",
            "#84CC16", "#22C55E", "#16A34A", "#1D4ED8", "#0891B2", "#0F766E", "#0E7490", "#2563EB",
            "#7C2D12", "#9A3412", "#BE123C", "#BE185D", "#C026D3", "#7E22CE", "#6D28D9", "#4338CA",
            "#1D4ED8", "#0369A1", "#155E75", "#166534", "#3F6212", "#A16207", "#B45309", "#C2410C",
            "#B91C1C", "#991B1B", "#7F1D1D", "#9F1239", "#831843", "#701A75", "#581C87", "#312E81",
            "#1E3A8A", "#1E40AF", "#1D3557", "#005F73", "#0A9396", "#94D2BD", "#EE9B00", "#CA6702",
            "#BB3E03", "#AE2012", "#9B2226", "#264653", "#2A9D8F", "#E76F51", "#6A4C93", "#1982C4",
            "#8AC926", "#FFCA3A", "#FF595E", "#FF924C", "#6A994E", "#386641", "#BC4749", "#4D908E",
        ]
        self.background_picker = ui.FilePicker(
            label="Upload Background",
            file_type="image",
            extensions=["png", "jpg", "jpeg", "webp", "gif", "bmp"],
            multiple=False,
            with_path=True,
            events=["result", "change"],
        )
        self.background_clear_button = ui.Button(
            text="Clear Background",
            class_name="gs-button gs-outline",
            variant="outlined",
            events=["click"],
            radius=10,
            border_width=1,
        )
        self.background_path_text = ui.Text(
            background_path if background_path else "No background image selected",
            font_size=11,
            color=self._MUTED,
        )
        self.background_opacity = ui.Slider(
            value=background_opacity,
            min=0,
            max=60,
            step=2,
            label="Background Opacity",
            helper_text="Controls how strongly the wallpaper shows through the shell.",
            events=["change"],
            width=280,
        )
        self.background_blur = ui.Slider(
            value=background_blur,
            min=0,
            max=24,
            step=1,
            label="Background Blur",
            helper_text="Lower values sharpen the wallpaper, higher values soften it live.",
            events=["change"],
            width=280,
        )
        self.translucent_panels = ui.Switch(
            value=translucent_panels,
            label="Translucent Panels",
            inline=True,
            events=["change"],
        )
        self.appearance_status = ui.Text("Appearance: idle", font_size=12, color=self._MUTED)

        self.runtime_model = ui.TextField(
            label="Model",
            class_name="gs-input",
            value=str(runtime.get("model", "qwen2.5-coder:7b")),
            events=["change"],
            width=320,
        )
        self.runtime_base_url = ui.TextField(
            label="Ollama Base URL",
            class_name="gs-input",
            value=str(runtime.get("ollama_base_url", "http://127.0.0.1:11434")),
            events=["change"],
            width=360,
        )
        self.runtime_models_dir = ui.TextField(
            label="Ollama Models Dir",
            class_name="gs-input",
            value=str(runtime.get("ollama_models_dir", "models/ollama")),
            events=["change"],
            width=360,
        )
        self.runtime_timeout = ui.TextField(
            label="Timeout (sec)",
            class_name="gs-input",
            value=str(runtime.get("request_timeout", 120)),
            events=["change"],
            width=160,
        )
        self.runtime_auto_pull = ui.Switch(
            value=bool(runtime.get("ollama_auto_pull", True)),
            label="Auto Pull Missing Model",
            inline=True,
            events=["change"],
        )
        self.runtime_save_button = ui.Button(
            text="Save Runtime",
            class_name="gs-button gs-primary",
            variant="filled",
            events=["click"],
            radius=10,
            font_weight="700",
        )
        self.runtime_health_button = ui.Button(
            text="Check Health",
            class_name="gs-button gs-outline",
            variant="outlined",
            events=["click"],
            radius=10,
            border_width=1,
        )
        self.runtime_status = ui.Text("Runtime: idle", font_size=12, color=self._MUTED)
        self.runtime_health = ui.Text("Health: unknown", font_size=12, color=self._MUTED)

    def build(self) -> ui.Column:
        self._header_surface = ui.Surface(
            ui.Row(
                ui.Icon(icon="settings", size=20, color=self._TEXT),
                ui.Column(self.title, self.subtitle, spacing=2),
                spacing=10,
                cross_axis="center",
            ),
            padding=14,
            class_name="gs-page-header",
            radius=14,
        )

        self._appearance_surface = ui.Surface(
            ui.Column(
                ui.Row(
                    ui.Icon(icon="palette", size=18, color=self._TEXT),
                    ui.Text("Appearance", font_size=15, font_weight="700", color=self._TEXT),
                    spacing=8,
                    cross_axis="center",
                ),
                self._build_accent_section(),
                ui.Row(self.background_picker, self.background_clear_button, spacing=10, cross_axis="center"),
                ui.Row(self.background_opacity, self.background_blur, spacing=12, cross_axis="center"),
                self.translucent_panels,
                self.background_path_text,
                self.appearance_status,
                spacing=10,
            ),
            padding=14,
            class_name="gs-card",
            radius=14,
            style={"overflow": "hidden"},
        )

        self._runtime_surface = ui.Surface(
            ui.Column(
                ui.Row(
                    ui.Icon(icon="memory", size=18, color=self._TEXT),
                    ui.Text("Runtime", font_size=15, font_weight="700", color=self._TEXT),
                    spacing=8,
                    cross_axis="center",
                ),
                self.runtime_model,
                self.runtime_base_url,
                self.runtime_models_dir,
                self.runtime_timeout,
                self.runtime_auto_pull,
                ui.Row(self.runtime_save_button, self.runtime_health_button, spacing=10),
                self.runtime_status,
                self.runtime_health,
                spacing=10,
            ),
            padding=14,
            class_name="gs-card",
            radius=14,
            style={"overflow": "hidden"},
        )

        return ui.ScrollableColumn(
            ui.Container(self._header_surface, padding={"left": 12, "right": 12, "top": 12, "bottom": 4}),
            ui.Container(self._appearance_surface, padding={"left": 12, "right": 12, "top": 4, "bottom": 8}),
            ui.Container(self._runtime_surface, padding={"left": 12, "right": 12, "top": 4, "bottom": 12}),
            spacing=0,
            expand=True,
        )

    def _build_accent_section(self) -> ui.Surface:
        accent_value = self.get_accent_color()
        self._accent_surface = ui.Surface(
            ui.Row(
                self.accent_preview,
                ui.Column(
                    ui.Text("Accent Surface", font_size=15, font_weight="700", color=self._TEXT),
                    ui.Spacer(),
                    self.accent_hint,
                    self.accent_value_text,
                    spacing=8,
                    cross_axis="center",
                ),
                ui.Spacer(),
                self.accent_open_button,
                spacing=14,
                cross_axis="center",
            ),
            padding={"left": 14, "right": 14, "top": 14, "bottom": 14},
            class_name="gs-accent-card",
            bgcolor=accent_value,
            border_color="#FFFFFF66",
            border_width=1,
            radius=14,
            style={
                "overflow": "hidden",
                "gradient": {
                    "colors": [accent_value, "#FFFFFF"],
                    "begin": "topLeft",
                    "end": "bottomRight",
                }
            },
        )
        return self._accent_surface

    def build_accent_overlay(self) -> ui.Overlay:
        self._accent_buttons.clear()
        swatch_rows: list[ui.Row] = []
        for start in range(0, len(self._accent_presets), 8):
            row_colors = self._accent_presets[start:start + 8]
            buttons: list[ui.Button] = []
            for color in row_colors:
                button = ui.Button(
                    text=" ",
                    class_name="gs-button",
                    variant="filled",
                    events=["click"],
                    width=44,
                    height=44,
                    radius=12,
                    bgcolor=color,
                    text_color=color,
                    border_color="#FFFFFF66",
                    border_width=1,
                    content_padding=0,
                )
                self._accent_buttons[color] = button
                buttons.append(button)
            swatch_rows.append(ui.Row(*buttons, spacing=8))

        self._accent_close_button = ui.Button(
            text="X",
            class_name="gs-button gs-outline gs-pill",
            variant="outlined",
            events=["click"],
            radius=999,
            width=40,
            height=40,
            font_weight="700",
        )
        self._accent_overlay_surface = ui.Surface(
            ui.Column(
                ui.Row(
                    ui.Icon(icon="palette", size=18, color=self._TEXT),
                    ui.Column(
                        ui.Text("Pick Accent", font_size=16, font_weight="700", color=self._TEXT),
                        ui.Text("Choose a swatch and the whole Genesis shell retints instantly.", font_size=11, color=self._MUTED),
                        spacing=2,
                    ),
                    spacing=10,
                    cross_axis="center",
                ),
                ui.Row(
                    self.accent_preview,
                    ui.Column(
                        ui.Text("Current Accent", font_size=12, font_weight="700", color=self._TEXT),
                        self.accent_value_text,
                        self.accent_hint,
                        spacing=4,
                    ),
                    spacing=12,
                    cross_axis="center",
                ),
                ui.Column(*swatch_rows, spacing=8),
                spacing=12,
            ),
            padding=16,
            class_name="gs-drawer",
            radius=18,
            style={"overflow": "hidden"},
        )
        self._refresh_accent_buttons(self.get_accent_color())
        return ui.Overlay(
            child=ui.Container(
                ui.Row(
                    ui.Column(
                        ui.Container(self._accent_overlay_surface, width=492),
                        self._accent_close_button,
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
            alignment="center",
            scrim_color="#78111C2D",
            transition_type="fade",
            transition_ms=220,
            events=["close"],
        )

    def bind_events(
        self,
        session,
        on_theme_change,
        on_runtime_save=None,
        on_runtime_health=None,
        on_accent_change=None,
        on_accent_overlay_open=None,
        on_accent_overlay_close=None,
        on_background_result=None,
        on_background_clear=None,
        on_background_opacity_change=None,
        on_background_blur_change=None,
        on_translucent_panels_change=None,
    ) -> None:
        self.theme_select.on_change(session, on_theme_change, inputs=[self.theme_select])
        if callable(on_accent_change):
            for color, button in self._accent_buttons.items():
                button.on_click(session, lambda _event=None, selected=color: on_accent_change(selected))
        if callable(on_accent_overlay_open):
            self.accent_open_button.on_click(session, on_accent_overlay_open)
        if callable(on_accent_overlay_close):
            self.get_accent_overlay().on_event(session, "close", on_accent_overlay_close)
            if self._accent_close_button is not None:
                self._accent_close_button.on_click(session, on_accent_overlay_close)
        if callable(on_background_result):
            self.background_picker.on_event(session, "result", on_background_result)
            self.background_picker.on_change(session, on_background_result)
        if callable(on_background_clear):
            self.background_clear_button.on_click(session, on_background_clear)
        if callable(on_runtime_save):
            self.runtime_save_button.on_click(session, on_runtime_save)
        if callable(on_runtime_health):
            self.runtime_health_button.on_click(session, on_runtime_health)
        if callable(on_background_opacity_change):
            self.background_opacity.on_change(session, on_background_opacity_change, inputs=[self.background_opacity])
        if callable(on_background_blur_change):
            self.background_blur.on_change(session, on_background_blur_change, inputs=[self.background_blur])
        if callable(on_translucent_panels_change):
            self.translucent_panels.on_change(session, on_translucent_panels_change, inputs=[self.translucent_panels])

    def apply_theme_change(self, value: str) -> str:
        theme = (value or "system").strip().lower()
        if theme not in {"light", "dark", "system"}:
            theme = "system"
        appearance = self._ensure_appearance_state()
        appearance["theme"] = theme
        self._save_settings()
        self.appearance_status.patch(text=f"Appearance saved: theme={theme}", color=self._MUTED)
        return theme

    def apply_accent_change(self, value: str) -> str:
        accent = str(value or "").strip() or self._ACCENT
        appearance = self._ensure_appearance_state()
        appearance["accent_color"] = accent
        self._save_settings()
        self.accent_preview.patch(value=accent)
        self.accent_value_text.patch(text=accent)
        self._refresh_accent_buttons(accent)
        if self._accent_surface is not None:
            self._accent_surface.patch(
                bgcolor=accent,
                border_color="#FFFFFF66",
                style={
                    "overflow": "hidden",
                    "gradient": {
                        "colors": [accent, "#FFFFFF"],
                        "begin": "topLeft",
                        "end": "bottomRight",
                    }
                },
            )
        self.appearance_status.patch(text=f"Accent saved: {accent}", color=self._MUTED)
        return accent

    def _refresh_accent_buttons(self, active_color: str) -> None:
        selected = str(active_color or "").strip().upper()
        for color, button in self._accent_buttons.items():
            is_selected = color.upper() == selected
            try:
                button.patch(
                    border_color="#FFFFFF" if is_selected else "#FFFFFF66",
                    border_width=3 if is_selected else 1,
                )
            except Exception:
                pass

    def set_background_path(self, path: str) -> str:
        normalized = str(path or "").strip()
        appearance = self._ensure_appearance_state()
        appearance["background_image"] = normalized
        self._save_settings()
        self.background_path_text.patch(
            text=normalized if normalized else "No background image selected",
            color=self._MUTED,
        )
        if normalized:
            self.appearance_status.patch(text="Background image applied", color=self._OK)
        else:
            self.appearance_status.patch(text="Background image cleared", color=self._MUTED)
        return normalized

    def apply_background_opacity_change(self, value: Any) -> int:
        if isinstance(value, dict):
            payload = value.get("payload") if isinstance(value.get("payload"), dict) else value
            value = payload.get("value", payload.get("data", payload.get("text", value)))
        try:
            opacity = int(float(value))
        except Exception:
            opacity = 24
        opacity = max(0, min(60, opacity))
        appearance = self._ensure_appearance_state()
        appearance["background_opacity"] = opacity
        self._save_settings()
        self.background_opacity.patch(value=opacity)
        self.appearance_status.patch(text=f"Background opacity saved: {opacity}%", color=self._MUTED)
        return opacity

    def apply_background_blur_change(self, value: Any) -> int:
        if isinstance(value, dict):
            payload = value.get("payload") if isinstance(value.get("payload"), dict) else value
            value = payload.get("value", payload.get("data", payload.get("text", value)))
        try:
            blur = int(float(value))
        except Exception:
            blur = 8
        blur = max(0, min(24, blur))
        appearance = self._ensure_appearance_state()
        appearance["background_blur"] = blur
        self._save_settings()
        self.background_blur.patch(value=blur)
        self.appearance_status.patch(text=f"Background blur saved: {blur}", color=self._MUTED)
        return blur

    def apply_translucent_panels_change(self, value: Any) -> bool:
        if isinstance(value, dict):
            payload = value.get("payload") if isinstance(value.get("payload"), dict) else value
            value = payload.get("value", payload.get("data", payload.get("text", value)))
        if isinstance(value, bool):
            enabled = value
        else:
            enabled = str(value).strip().lower() in {"1", "true", "yes", "on"}
        appearance = self._ensure_appearance_state()
        appearance["translucent_panels"] = enabled
        self._save_settings()
        self.translucent_panels.patch(value=enabled)
        self.appearance_status.patch(
            text="Translucent panels enabled" if enabled else "Translucent panels disabled",
            color=self._MUTED,
        )
        return enabled

    def clear_background_path(self) -> None:
        self.set_background_path("")

    def get_background_path(self) -> str:
        appearance = self._state.get("appearance", {})
        if not isinstance(appearance, dict):
            return ""
        return str(appearance.get("background_image", "")).strip()

    def get_accent_color(self) -> str:
        appearance = self._state.get("appearance", {})
        if not isinstance(appearance, dict):
            return self._ACCENT
        value = str(appearance.get("accent_color", self._ACCENT)).strip()
        return value or self._ACCENT

    def get_background_opacity(self) -> int:
        appearance = self._state.get("appearance", {})
        if not isinstance(appearance, dict):
            return 24
        try:
            value = int(float(appearance.get("background_opacity", 24)))
        except Exception:
            value = 24
        return max(0, min(60, value))

    def get_background_blur(self) -> int:
        appearance = self._state.get("appearance", {})
        if not isinstance(appearance, dict):
            return 8
        try:
            value = int(float(appearance.get("background_blur", 8)))
        except Exception:
            value = 8
        return max(0, min(24, value))

    def use_translucent_panels(self) -> bool:
        appearance = self._state.get("appearance", {})
        if not isinstance(appearance, dict):
            return True
        return bool(appearance.get("translucent_panels", True))

    def get_accent_overlay(self) -> ui.Overlay:
        if not hasattr(self, "_accent_overlay"):
            self._accent_overlay = self.build_accent_overlay()
        return self._accent_overlay

    def get_runtime_config(self, session=None) -> dict[str, Any]:
        model = self._read_control_value(self.runtime_model, "qwen2.5-coder:7b", session=session)
        base_url = self._read_control_value(self.runtime_base_url, "http://127.0.0.1:11434", session=session)
        models_dir = self._read_control_value(self.runtime_models_dir, "models/ollama", session=session)
        timeout_raw = self._read_control_value(self.runtime_timeout, "120", session=session)
        auto_pull = self._read_bool_value(self.runtime_auto_pull, True, session=session)
        runtime = self._state.get("runtime", {})
        preferred_shell = str(runtime.get("preferred_shell", "auto")).strip() if isinstance(runtime, dict) else "auto"
        try:
            timeout_value = max(5.0, float(timeout_raw))
        except Exception:
            timeout_value = 120.0
        return {
            "model": model.strip() or "qwen2.5-coder:7b",
            "ollama_base_url": base_url.strip().rstrip("/") or "http://127.0.0.1:11434",
            "request_timeout": timeout_value,
            "ollama_models_dir": models_dir.strip() or "models/ollama",
            "ollama_auto_pull": bool(auto_pull),
            "preferred_shell": preferred_shell or "auto",
        }

    def apply_runtime_change(self, config: dict[str, Any]) -> dict[str, Any]:
        runtime = self._state.setdefault("runtime", {})
        if not isinstance(runtime, dict):
            runtime = {}
            self._state["runtime"] = runtime

        model = str(config.get("model", "qwen2.5-coder:7b")).strip() or "qwen2.5-coder:7b"
        base_url = str(config.get("ollama_base_url", "http://127.0.0.1:11434")).strip().rstrip("/")
        if not base_url:
            base_url = "http://127.0.0.1:11434"
        models_dir = str(config.get("ollama_models_dir", "models/ollama")).strip() or "models/ollama"
        auto_pull = bool(config.get("ollama_auto_pull", True))
        shell = str(config.get("preferred_shell", "auto")).strip() or "auto"
        try:
            timeout_value = max(5.0, float(config.get("request_timeout", 120.0)))
        except Exception:
            timeout_value = 120.0

        runtime["model"] = model
        runtime["ollama_base_url"] = base_url
        runtime["request_timeout"] = timeout_value
        runtime["ollama_models_dir"] = models_dir
        runtime["ollama_auto_pull"] = auto_pull
        runtime["preferred_shell"] = shell
        self._save_settings()

        self.runtime_model.patch(value=model)
        self.runtime_base_url.patch(value=base_url)
        self.runtime_models_dir.patch(value=models_dir)
        self.runtime_timeout.patch(value=str(timeout_value))
        self.runtime_auto_pull.patch(value=auto_pull)
        self.runtime_status.patch(text=f"Runtime saved: {model} @ {base_url} (models={models_dir})")

        return {
            "model": model,
            "ollama_base_url": base_url,
            "request_timeout": timeout_value,
            "ollama_models_dir": models_dir,
            "ollama_auto_pull": auto_pull,
            "preferred_shell": shell,
        }

    def set_appearance_status(self, text: str, *, error: bool = False) -> None:
        self.appearance_status.patch(
            text=text.strip() or "Appearance: idle",
            color=self._ERROR if error else self._MUTED,
        )

    def set_runtime_status(self, text: str) -> None:
        self.runtime_status.patch(text=text.strip() or "Runtime: idle")

    def set_runtime_health(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            self.runtime_health.patch(text="Health: unavailable", color=self._ERROR)
            return
        ok = bool(payload.get("ok", False))
        reachable = payload.get("ollama_reachable")
        model = str(payload.get("model", "")).strip()
        model_loaded = payload.get("model_loaded")
        if ok:
            reachable_text = "reachable" if reachable else "unknown"
            loaded_text = "loaded" if model_loaded else "not loaded"
            self.runtime_health.patch(
                text=f"Health: ok ({reachable_text}, model={model} {loaded_text})",
                color=self._OK,
            )
            return
        error = str(payload.get("error", "runtime unavailable")).strip()
        self.runtime_health.patch(text=f"Health: error ({error})", color=self._ERROR)

    def set_glass_mode(self, enabled: bool) -> None:
        self._glass_mode = bool(enabled)

    def set_palette(self, palette: dict[str, str]) -> None:
        self._SURFACE = palette.get("surface", self._SURFACE)
        self._SURFACE_ALT = palette.get("surface_alt", self._SURFACE_ALT)
        self._BORDER = palette.get("border", self._BORDER)
        self._TEXT = palette.get("text", self._TEXT)
        self._MUTED = palette.get("muted", self._MUTED)
        self._ACCENT = palette.get("accent", self._ACCENT)

        accent_text = text_on(self._ACCENT)
        try:
            self.title.patch(color=self._TEXT)
            self.subtitle.patch(color=self._MUTED)
            self.background_path_text.patch(color=self._MUTED)
            self.accent_value_text.patch(color=self._TEXT)
            self.accent_hint.patch(color=self._MUTED)
            self.runtime_status.patch(color=self._MUTED)
            if self._accent_surface is not None:
                self._accent_surface.patch(
                    bgcolor=self._ACCENT,
                    style={
                        "overflow": "hidden",
                        "gradient": {
                            "colors": [self._ACCENT, self._SURFACE],
                            "begin": "topLeft",
                            "end": "bottomRight",
                        },
                    },
                )
            self.accent_preview.patch(border_color=palette.get("border", self._BORDER))
        except Exception:
            pass

    def _ensure_appearance_state(self) -> dict[str, Any]:
        appearance = self._state.setdefault("appearance", {})
        if not isinstance(appearance, dict):
            appearance = {}
            self._state["appearance"] = appearance
        return appearance

    def _load_settings(self) -> dict[str, Any]:
        default = {
            "appearance": {
                "theme": "system",
                "accent_color": self._ACCENT,
                "background_image": "",
                "background_opacity": 24,
                "background_blur": 8,
                "translucent_panels": True,
            },
            "runtime": {
                "host": "127.0.0.1",
                "preferred_port": 9988,
                "max_port_scan": 12,
                "db_path": "data/genesis.sqlite",
                "ollama_base_url": "http://127.0.0.1:11434",
                "model": "qwen2.5-coder:7b",
                "request_timeout": 120.0,
                "ollama_models_dir": "models/ollama",
                "ollama_auto_pull": True,
                "preferred_shell": "auto",
            },
        }
        if not self.settings_file.exists():
            return default
        try:
            payload = json.loads(self.settings_file.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                merged = default
                appearance = payload.get("appearance")
                runtime = payload.get("runtime")
                if isinstance(appearance, dict):
                    merged["appearance"].update(appearance)
                if isinstance(runtime, dict):
                    merged["runtime"].update(runtime)
                return merged
        except Exception:
            pass
        return default

    def _save_settings(self) -> None:
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        self.settings_file.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_control_value(self, control: Any, fallback: str, session=None) -> str:
        if session is not None:
            try:
                value = session.get_value(control, prop="value")
                if value is not None:
                    return str(value)
            except Exception:
                pass
        try:
            props = control.to_dict().get("props", {})
            value = props.get("value", fallback)
            return str(value)
        except Exception:
            return str(fallback)

    def _read_bool_value(self, control: Any, fallback: bool, session=None) -> bool:
        if session is not None:
            try:
                value = session.get_value(control, prop="value")
                if isinstance(value, bool):
                    return value
                if value is not None:
                    raw = str(value).strip().lower()
                    if raw in {"1", "true", "yes", "on"}:
                        return True
                    if raw in {"0", "false", "no", "off"}:
                        return False
            except Exception:
                pass
        try:
            props = control.to_dict().get("props", {})
            value = props.get("value", fallback)
            if isinstance(value, bool):
                return value
            raw = str(value).strip().lower()
            if raw in {"1", "true", "yes", "on"}:
                return True
            if raw in {"0", "false", "no", "off"}:
                return False
        except Exception:
            pass
        return bool(fallback)
