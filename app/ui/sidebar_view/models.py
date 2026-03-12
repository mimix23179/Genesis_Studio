from __future__ import annotations

from typing import Any, Callable, Optional

import butterflyui as ui


class ModelsSidebar:
    _BG = "#F7F7F8"
    _SURFACE = "#FFFFFF"
    _SURFACE_ALT = "#F8FAFC"
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
        self._on_refresh: Optional[Callable[[], None]] = None
        self._on_select_model: Optional[Callable[[str], None]] = None
        self._model_buttons: dict[str, ui.Button] = {}
        self._active_model = ""
        self._installed_models: list[str] = []
        self._catalog_entries: list[dict[str, Any]] = []
        self._current_detail: dict[str, Any] | None = None
        self._catalog_page = 1
        self._catalog_page_count = 1

        self.title = ui.Text("Models", font_size=16, font_weight="700", color=self._TEXT)
        self.subtitle = ui.Text("Quick library controls", font_size=11, color=self._MUTED)
        self.refresh_button = ui.GlyphButton(
            glyph="refresh",
            tooltip="Refresh models",
            events=["click"],
            color=self._TEXT,
            size="20",
        )
        self.list_column = ui.ScrollableColumn(
            spacing=10,
            content_padding={"left": 8, "right": 8, "top": 8, "bottom": 12},
        )

    def on_refresh(self, callback: Callable[[], None]) -> None:
        self._on_refresh = callback

    def on_select_model(self, callback: Callable[[str], None]) -> None:
        self._on_select_model = callback

    def bind_events(self, session) -> None:
        self._bound_session = session
        self.refresh_button.on_click(session, self._handle_refresh)
        self._bind_model_buttons()

    def set_state(
        self,
        *,
        active_model: str,
        installed_models: list[str],
        catalog_entries: list[dict[str, Any]],
        current_detail: dict[str, Any] | None,
        catalog_page: int,
        catalog_page_count: int,
    ) -> None:
        self._active_model = str(active_model or "").strip()
        self._installed_models = [str(item).strip() for item in installed_models if str(item).strip()]
        self._catalog_entries = list(catalog_entries)
        self._current_detail = current_detail
        self._catalog_page = max(1, int(catalog_page or 1))
        self._catalog_page_count = max(1, int(catalog_page_count or 1))
        self._rebuild_list()

    def build(self) -> ui.Container:
        header = ui.Container(
            ui.Row(
                ui.Column(self.title, self.subtitle, spacing=2),
                ui.Spacer(),
                self.refresh_button,
                spacing=8,
                cross_axis="center",
            ),
            padding={"left": 16, "right": 12, "top": 16, "bottom": 8},
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
        self._SURFACE_ALT = palette.get("surface_alt", self._SURFACE_ALT)
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
            self.refresh_button.patch(color=self._TEXT)
        except Exception:
            pass
        self._rebuild_list()

    def _rebuild_list(self) -> None:
        self.list_column.children.clear()
        self._model_buttons.clear()

        installed_count = len(self._installed_models)
        suggestion_names: list[str] = []
        for item in self._catalog_entries:
            name = str(item.get("name", "")).strip()
            if name and name not in self._installed_models:
                suggestion_names.append(name)
            if len(suggestion_names) >= 4:
                break

        stats_card = ui.Surface(
            ui.Column(
                ui.Text("Runtime Snapshot", font_size=13, font_weight="700", color=self._TEXT),
                ui.Text(f"Active model: {self._active_model or 'None'}", font_size=11, color=self._MUTED),
                ui.Text(f"Installed locally: {installed_count}", font_size=11, color=self._MUTED),
                ui.Text(f"Catalog page: {self._catalog_page} / {self._catalog_page_count}", font_size=11, color=self._MUTED),
                spacing=4,
            ),
            padding=12,
            class_name="gs-card",
            radius=12,
        )
        self.list_column.children.append(stats_card)

        if self._current_detail:
            detail_name = str(self._current_detail.get("name", "")).strip() or "Current focus"
            detail_description = str(self._current_detail.get("description", "")).strip() or "Detail opened in the main model workspace."
            self.list_column.children.append(
                ui.Surface(
                    ui.Column(
                        ui.Text("Detail Focus", font_size=13, font_weight="700", color=self._TEXT),
                        ui.Text(detail_name, font_size=12, font_weight="700", color=self._ACCENT),
                        ui.Text(detail_description, font_size=11, color=self._MUTED),
                        spacing=4,
                    ),
                    padding=12,
                    class_name="gs-card",
                    radius=12,
                )
            )

        self.list_column.children.append(ui.Text("Installed Models", font_size=12, font_weight="700", color=self._TEXT))
        if not self._installed_models:
            self.list_column.children.append(ui.Text("No pulled models yet.", font_size=11, color=self._MUTED))
        else:
            for name in self._installed_models[:8]:
                is_active = name == self._active_model
                button = ui.Button(
                    text=name,
                    class_name="gs-button gs-sidebar-item-active" if is_active else "gs-button gs-sidebar-item",
                    variant="filled" if is_active else "outlined",
                    events=["click"],
                    radius=10,
                    width=self.width - 40,
                    font_weight="700" if is_active else "600",
                )
                self._model_buttons[f"installed::{name}"] = button
                self.list_column.children.append(button)

        self.list_column.children.append(ui.Text("Suggested Pulls", font_size=12, font_weight="700", color=self._TEXT))
        if not suggestion_names:
            self.list_column.children.append(ui.Text("Library suggestions will appear after refresh.", font_size=11, color=self._MUTED))
        else:
            for name in suggestion_names:
                button = ui.Button(
                    text=name,
                    class_name="gs-button gs-sidebar-item",
                    variant="outlined",
                    events=["click"],
                    radius=10,
                    width=self.width - 40,
                    font_weight="600",
                )
                self._model_buttons[f"suggested::{name}"] = button
                self.list_column.children.append(button)

        self._bind_model_buttons()

    def _bind_model_buttons(self) -> None:
        if self._bound_session is None:
            return
        for key, button in self._model_buttons.items():
            _, _, model_name = key.partition("::")
            button.on_click(self._bound_session, lambda _event=None, selected=model_name: self._select_model(selected))

    def _handle_refresh(self, _event=None) -> None:
        if callable(self._on_refresh):
            self._on_refresh()

    def _select_model(self, model_name: str) -> None:
        if callable(self._on_select_model):
            self._on_select_model(model_name)
