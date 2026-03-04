from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import butterflyui as ui


class SettingsPage:
    _SURFACE = "#FFFFFF"
    _BORDER = "#D1D5DB"
    _TEXT = "#111827"
    _MUTED = "#6B7280"
    _ACCENT = "#10A37F"

    def __init__(self, settings_file: Path) -> None:
        self.settings_file = settings_file
        self._state: dict[str, Any] = self._load_settings()

        self.title = ui.Text("Settings", font_size=22, font_weight="700", color=self._TEXT)
        self.subtitle = ui.Text("Appearance and Runtime", font_size=12, color=self._MUTED)

        appearance = self._state.get("appearance", {}) if isinstance(self._state.get("appearance"), dict) else {}
        theme_value = str(appearance.get("theme", "light"))
        runtime = self._state.get("runtime", {}) if isinstance(self._state.get("runtime"), dict) else {}

        self.theme_select = ui.Select(
            label="Theme",
            value=theme_value,
            options=[
                {"label": "Light", "value": "light"},
                {"label": "Dark", "value": "dark"},
                {"label": "System", "value": "system"},
            ],
            events=["change"],
            width=220,
        )
        self.status = ui.Text("Idle", font_size=12, color=self._MUTED)

        self.runtime_model = ui.TextField(
            label="Model",
            value=str(runtime.get("model", "qwen2.5-coder:7b")),
            events=["change"],
            width=300,
        )
        self.runtime_base_url = ui.TextField(
            label="Ollama Base URL",
            value=str(runtime.get("ollama_base_url", "http://127.0.0.1:11434")),
            events=["change"],
            width=340,
        )
        self.runtime_timeout = ui.TextField(
            label="Timeout (sec)",
            value=str(runtime.get("request_timeout", 120)),
            events=["change"],
            width=140,
        )
        self.runtime_shell = ui.Select(
            label="Terminal Shell",
            value=str(runtime.get("preferred_shell", "auto")),
            options=[
                {"label": "Auto", "value": "auto"},
                {"label": "PowerShell 7 (pwsh)", "value": "pwsh"},
                {"label": "Windows PowerShell", "value": "powershell"},
                {"label": "Command Prompt (cmd)", "value": "cmd"},
                {"label": "Bash", "value": "bash"},
                {"label": "Zsh", "value": "zsh"},
                {"label": "Sh", "value": "sh"},
            ],
            events=["change"],
            width=220,
        )
        self.runtime_save_button = ui.Button(
            text="Save Runtime",
            variant="filled",
            events=["click"],
            bgcolor=self._ACCENT,
            text_color="#FFFFFF",
            border_color=self._ACCENT,
            border_width=1,
            radius=10,
            font_weight="700",
        )
        self.runtime_health_button = ui.Button(
            text="Check Health",
            variant="outlined",
            events=["click"],
            radius=10,
            border_width=1,
        )
        self.runtime_status = ui.Text("Runtime: idle", font_size=12, color=self._MUTED)
        self.runtime_health = ui.Text("Health: unknown", font_size=12, color=self._MUTED)

    def build(self) -> ui.Column:
        header = ui.Surface(
            ui.Column(self.title, self.subtitle, spacing=2),
            padding=14,
            bgcolor=self._SURFACE,
            border_color=self._BORDER,
            border_width=1,
            radius=12,
        )

        appearance_card = ui.Surface(
            ui.Column(self.theme_select, self.status, spacing=10),
            padding=14,
            bgcolor=self._SURFACE,
            border_color=self._BORDER,
            border_width=1,
            radius=12,
        )

        runtime_card = ui.Surface(
            ui.Column(
                ui.Text("Runtime", font_size=14, font_weight="700", color=self._TEXT),
                self.runtime_model,
                self.runtime_base_url,
                ui.Row(self.runtime_timeout, self.runtime_shell, spacing=10, cross_axis="end"),
                ui.Row(self.runtime_save_button, self.runtime_health_button, spacing=10),
                self.runtime_status,
                self.runtime_health,
                spacing=10,
            ),
            padding=14,
            bgcolor=self._SURFACE,
            border_color=self._BORDER,
            border_width=1,
            radius=12,
        )

        return ui.Column(
            ui.Container(header, padding={"left": 12, "right": 12, "top": 12, "bottom": 4}),
            ui.Container(appearance_card, padding={"left": 12, "right": 12, "top": 4, "bottom": 12}),
            ui.Container(runtime_card, padding={"left": 12, "right": 12, "top": 0, "bottom": 12}),
            expand=True,
            spacing=0,
        )

    def bind_events(
        self,
        session,
        on_theme_change,
        on_runtime_save=None,
        on_runtime_health=None,
        on_runtime_shell_change=None,
    ) -> None:
        self.theme_select.on_change(session, on_theme_change, inputs=[self.theme_select])
        if callable(on_runtime_save):
            self.runtime_save_button.on_click(session, on_runtime_save)
        if callable(on_runtime_health):
            self.runtime_health_button.on_click(session, on_runtime_health)
        if callable(on_runtime_shell_change):
            self.runtime_shell.on_change(session, on_runtime_shell_change, inputs=[self.runtime_shell])

    def apply_theme_change(self, value: str) -> str:
        theme = (value or "light").strip().lower()
        if theme not in {"light", "dark", "system"}:
            theme = "light"

        appearance = self._state.setdefault("appearance", {})
        if not isinstance(appearance, dict):
            appearance = {}
            self._state["appearance"] = appearance
        appearance["theme"] = theme

        self._save_settings()
        self.status.patch(text=f"Saved appearance theme: {theme}")
        return theme

    def get_runtime_config(self, session=None) -> dict[str, Any]:
        model = self._read_control_value(self.runtime_model, "qwen2.5-coder:7b", session=session)
        base_url = self._read_control_value(self.runtime_base_url, "http://127.0.0.1:11434", session=session)
        timeout_raw = self._read_control_value(self.runtime_timeout, "120", session=session)
        shell = self._read_control_value(self.runtime_shell, "auto", session=session)
        try:
            timeout_value = max(5.0, float(timeout_raw))
        except Exception:
            timeout_value = 120.0
        return {
            "model": model.strip() or "qwen2.5-coder:7b",
            "ollama_base_url": base_url.strip().rstrip("/") or "http://127.0.0.1:11434",
            "request_timeout": timeout_value,
            "preferred_shell": (shell.strip() or "auto"),
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
        shell = str(config.get("preferred_shell", "auto")).strip() or "auto"
        try:
            timeout_value = max(5.0, float(config.get("request_timeout", 120.0)))
        except Exception:
            timeout_value = 120.0

        runtime["model"] = model
        runtime["ollama_base_url"] = base_url
        runtime["request_timeout"] = timeout_value
        runtime["preferred_shell"] = shell

        self._save_settings()

        self.runtime_model.patch(value=model)
        self.runtime_base_url.patch(value=base_url)
        self.runtime_timeout.patch(value=str(timeout_value))
        self.runtime_shell.patch(value=shell)
        self.runtime_status.patch(text=f"Runtime saved: {model} @ {base_url}")

        return {
            "model": model,
            "ollama_base_url": base_url,
            "request_timeout": timeout_value,
            "preferred_shell": shell,
        }

    def set_runtime_status(self, text: str) -> None:
        self.runtime_status.patch(text=text.strip() or "Runtime: idle")

    def set_runtime_health(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            self.runtime_health.patch(text="Health: unavailable", color="#B91C1C")
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
                color="#047857",
            )
            return
        error = str(payload.get("error", "runtime unavailable")).strip()
        self.runtime_health.patch(
            text=f"Health: error ({error})",
            color="#B91C1C",
        )

    def _load_settings(self) -> dict[str, Any]:
        default = {
            "appearance": {"theme": "light"},
            "runtime": {
                "host": "127.0.0.1",
                "preferred_port": 9988,
                "max_port_scan": 12,
                "db_path": "data/genesis.sqlite",
                "ollama_base_url": "http://127.0.0.1:11434",
                "model": "qwen2.5-coder:7b",
                "request_timeout": 120.0,
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
