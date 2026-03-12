from __future__ import annotations

from typing import Any, Callable, Optional

import butterflyui as ui


class SettingsSidebar:
    _BG = "#F7F7F8"
    _SURFACE = "#FFFFFF"
    _BORDER = "#E5E7EB"
    _TEXT = "#0F172A"
    _MUTED = "#475569"
    _ACCENT = "#10A37F"
    _ACTIVE_BG = "#DCE6FF"
    _ACTIVE_TEXT = "#0B1220"
    _ON_ACCENT = "#FFFFFF"

    def __init__(self, width: int = 280) -> None:
        self.width = width
        self._list_height = 620
        self._glass_mode = False
        self._root_container: ui.Container | None = None
        self._list_host: ui.Container | None = None
        self._bound_session: Any = None
        self._on_select: Optional[Callable[[str], None]] = None
        self._section_buttons: dict[str, ui.Button] = {}
        self._active_section = "appearance"
        self._sections = [
            ("appearance", "Appearance"),
            ("runtime", "Runtime"),
            ("profiles", "Profiles"),
            ("workspace", "Workspace"),
            ("assistant", "Assistant"),
            ("downloads", "Downloads"),
            ("integrations", "Integrations"),
            ("privacy", "Privacy"),
            ("shortcuts", "Shortcuts"),
            ("advanced", "Advanced"),
        ]

        self.title = ui.Text("Settings", font_size=16, font_weight="700", color=self._TEXT)
        self.subtitle = ui.Text("Sections roadmap", font_size=11, color=self._MUTED)
        self.summary = ui.Text("10 sections ready for expansion", font_size=11, color=self._MUTED)
        self.list_column = ui.ScrollableColumn(
            spacing=8,
            content_padding={"left": 8, "right": 8, "top": 8, "bottom": 12},
        )

    def on_select(self, callback: Callable[[str], None]) -> None:
        self._on_select = callback

    def bind_events(self, session) -> None:
        self._bound_session = session
        self._bind_section_buttons()

    def set_active_section(self, key: str) -> None:
        target = str(key or "").strip() or self._active_section
        if target != self._active_section:
            self._active_section = target
            self._rebuild_list()

    def build(self) -> ui.Container:
        header = ui.Container(
            ui.Column(self.title, self.subtitle, self.summary, spacing=2),
            padding={"left": 16, "right": 16, "top": 16, "bottom": 8},
        )
        self._list_host = ui.Container(
            self.list_column,
            height=self._list_height,
            padding={"left": 0, "right": 0, "top": 0, "bottom": 0},
        )
        self._rebuild_list()
        self._root_container = ui.Container(
            ui.Column(header, self._list_host, ui.Spacer(), spacing=0, expand=True),
            width=self.width,
            class_name="gs-sidebar",
            style={"border_right": f"1px solid {self._BORDER}"},
        )
        return self._root_container

    def set_glass_mode(self, enabled: bool) -> None:
        self._glass_mode = bool(enabled)
        self._rebuild_list()

    def set_palette(self, palette: dict[str, str]) -> None:
        self._BG = palette.get("bg", self._BG)
        self._SURFACE = palette.get("surface", self._SURFACE)
        self._BORDER = palette.get("border", self._BORDER)
        self._TEXT = palette.get("text", self._TEXT)
        self._MUTED = palette.get("muted", self._MUTED)
        self._ACCENT = palette.get("accent", self._ACCENT)
        self._ACTIVE_BG = palette.get("active_bg", self._ACTIVE_BG)
        self._ACTIVE_TEXT = palette.get("active_text", self._ACTIVE_TEXT)
        self._ON_ACCENT = palette.get("on_accent", self._ON_ACCENT)

        try:
            self.title.patch(color=self._TEXT)
            self.subtitle.patch(color=self._MUTED)
            self.summary.patch(color=self._MUTED)
        except Exception:
            pass

        self._rebuild_list()

    def _rebuild_list(self) -> None:
        self.list_column.children.clear()
        self._section_buttons.clear()

        for key, label in self._sections:
            is_active = key == self._active_section
            button = ui.Button(
                text=label,
                class_name="gs-button gs-sidebar-item-active" if is_active else "gs-button gs-sidebar-item",
                variant="filled" if is_active else "outlined",
                events=["click"],
                radius=10,
                width=self.width - 40,
                font_weight="700" if is_active else "600",
            )
            self._section_buttons[key] = button
            self.list_column.children.append(button)

        self._bind_section_buttons()

    def _bind_section_buttons(self) -> None:
        if self._bound_session is None:
            return
        for key, button in self._section_buttons.items():
            button.on_click(self._bound_session, lambda _event=None, selected=key: self._select(selected))

    def _select(self, key: str) -> None:
        self._active_section = key
        self._rebuild_list()
        if callable(self._on_select):
            self._on_select(key)
