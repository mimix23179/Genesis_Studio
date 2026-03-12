from __future__ import annotations

from typing import Any, Callable, Optional

import butterflyui as ui


class DownloadsSidebar:
    _BG = "#F7F7F8"
    _SURFACE = "#FFFFFF"
    _SURFACE_ALT = "#F8FAFC"
    _BORDER = "#E5E7EB"
    _TEXT = "#0F172A"
    _MUTED = "#475569"
    _ACCENT = "#10A37F"

    def __init__(self, width: int = 280) -> None:
        self.width = width
        self._list_height = 620
        self._glass_mode = False
        self._root_container: ui.Container | None = None
        self._list_host: ui.Container | None = None
        self._bound_session: Any = None
        self._on_refresh: Optional[Callable[[], None]] = None
        self._downloads: list[dict[str, Any]] = []
        self._banner = "No active downloads"
        self._completed_history: list[dict[str, Any]] = []

        self.title = ui.Text("Downloads", font_size=16, font_weight="700", color=self._TEXT)
        self.subtitle = ui.Text("Queue and recent completions", font_size=11, color=self._MUTED)
        self.refresh_button = ui.GlyphButton(
            glyph="refresh",
            tooltip="Refresh downloads",
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

    def bind_events(self, session) -> None:
        self._bound_session = session
        self.refresh_button.on_click(session, self._handle_refresh)

    def set_state(self, *, downloads: list[dict[str, Any]], banner: str, completed_history: list[dict[str, Any]]) -> None:
        self._downloads = list(downloads)
        self._banner = str(banner or "").strip() or "No active downloads"
        self._completed_history = list(completed_history)
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
        try:
            self.title.patch(color=self._TEXT)
            self.subtitle.patch(color=self._MUTED)
            self.refresh_button.patch(color=self._TEXT)
        except Exception:
            pass
        self._rebuild_list()

    def _rebuild_list(self) -> None:
        self.list_column.children.clear()

        active_count = 0
        paused_count = 0
        completed_count = 0
        active_items: list[dict[str, Any]] = []
        for item in self._downloads:
            done = bool(item.get("done", False))
            paused = bool(item.get("paused", False))
            error = str(item.get("error", "")).strip()
            if done and not error:
                completed_count += 1
            elif paused:
                paused_count += 1
                active_items.append(item)
            else:
                active_count += 1
                active_items.append(item)

        self.list_column.children.append(
            ui.Surface(
                ui.Column(
                    ui.Text("Queue Snapshot", font_size=13, font_weight="700", color=self._TEXT),
                    ui.Text(self._banner, font_size=11, color=self._MUTED),
                    ui.Text(f"Active {active_count} | Paused {paused_count} | Completed {completed_count}", font_size=11, color=self._MUTED),
                    spacing=4,
                ),
                padding=12,
                class_name="gs-card",
                radius=12,
            )
        )

        self.list_column.children.append(ui.Text("Active Queue", font_size=12, font_weight="700", color=self._TEXT))
        if not active_items:
            self.list_column.children.append(ui.Text("No active or paused downloads.", font_size=11, color=self._MUTED))
        else:
            for item in active_items[:5]:
                model = str(item.get("model", "Unknown model")).strip() or "Unknown model"
                status = str(item.get("status", "Queued")).strip() or "Queued"
                progress = item.get("progress_percent")
                progress_text = f"{progress}%" if isinstance(progress, int) else "waiting"
                self.list_column.children.append(
                    ui.Surface(
                        ui.Column(
                            ui.Text(model, font_size=12, font_weight="700", color=self._TEXT),
                            ui.Text(f"{status} | {progress_text}", font_size=11, color=self._MUTED),
                            spacing=3,
                        ),
                        padding=12,
                        class_name="gs-card",
                        radius=12,
                    )
                )

        self.list_column.children.append(ui.Text("Recent Completed", font_size=12, font_weight="700", color=self._TEXT))
        if not self._completed_history:
            self.list_column.children.append(ui.Text("Completed downloads will appear here.", font_size=11, color=self._MUTED))
        else:
            for entry in self._completed_history[:6]:
                model = str(entry.get("model", "Unknown model")).strip() or "Unknown model"
                completed_at = str(entry.get("completed_at", "Just now")).strip() or "Just now"
                note = str(entry.get("note", "Ready to load from the Installed drawer.")).strip() or "Ready to load from the Installed drawer."
                self.list_column.children.append(
                    ui.Surface(
                        ui.Column(
                            ui.Text(model, font_size=12, font_weight="700", color=self._ACCENT),
                            ui.Text(completed_at, font_size=11, color=self._MUTED),
                            ui.Text(note, font_size=11, color=self._MUTED),
                            spacing=3,
                        ),
                        padding=12,
                        class_name="gs-card",
                        radius=12,
                    )
                )

    def _handle_refresh(self, _event=None) -> None:
        if callable(self._on_refresh):
            self._on_refresh()
