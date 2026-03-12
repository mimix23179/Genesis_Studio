from __future__ import annotations

from typing import Any, Callable

import butterflyui as ui


class DownloadsPageView:
    """Downloads workspace page with live progress and pause/resume controls."""

    _BG = "#F6F8FC"
    _SURFACE = "#FFFFFF"
    _SURFACE_ALT = "#F8FAFC"
    _BORDER = "#D6DEE8"
    _TEXT = "#0F172A"
    _MUTED = "#64748B"
    _ACCENT = "#10A37F"
    _SUCCESS = "#047857"
    _ERROR = "#B91C1C"

    def __init__(self) -> None:
        self._bound_session: Any = None
        self._on_refresh: Callable[[], None] | None = None
        self._on_pause: Callable[[str], None] | None = None
        self._on_resume: Callable[[str], None] | None = None
        self._row_buttons: dict[str, tuple[ui.Button, ui.Button]] = {}
        self._root_container: ui.Container | None = None
        self._glass_mode = False
        self._header_surface: ui.Surface | None = None
        self._body_surface: ui.Surface | None = None

        self.title = ui.Text("Downloads", font_size=22, font_weight="700", color=self._TEXT)
        self.subtitle = ui.Text(
            "Track Ollama pulls, pause active work, and resume paused downloads.",
            font_size=12,
            color=self._MUTED,
        )
        self.status = ui.Text("Downloads idle", font_size=12, color=self._MUTED)
        self.summary = ui.Text("No downloads yet", font_size=12, color=self._MUTED)
        self.refresh_button = ui.Button(
            text="Refresh",
            class_name="gs-button gs-outline",
            variant="outlined",
            events=["click"],
            radius=10,
        )
        self.list_column = ui.ScrollableColumn(
            spacing=12,
            expand=True,
            content_padding={"left": 4, "right": 4, "top": 4, "bottom": 12},
        )

    def bind_events(
        self,
        session,
        *,
        on_refresh: Callable[[], None],
        on_pause: Callable[[str], None],
        on_resume: Callable[[str], None],
    ) -> None:
        self._bound_session = session
        self._on_refresh = on_refresh
        self._on_pause = on_pause
        self._on_resume = on_resume
        self.refresh_button.on_click(session, self._handle_refresh)
        self._bind_row_events()

    def build(self) -> ui.Container:
        self._header_surface = ui.Surface(
            ui.Row(
                ui.Column(self.title, self.subtitle, self.status, spacing=4),
                ui.Spacer(),
                self.refresh_button,
                spacing=12,
                cross_axis="start",
            ),
            padding=16,
            class_name="gs-page-header",
            radius=14,
        )
        self._body_surface = ui.Surface(
            ui.Column(
                ui.Container(self.summary, padding={"left": 4, "right": 4, "top": 4, "bottom": 8}),
                ui.Expanded(self.list_column),
                spacing=0,
                expand=True,
            ),
            padding=14,
            class_name="gs-card",
            radius=14,
        )
        self._root_container = ui.Container(
            ui.Column(
                ui.Container(self._header_surface, padding={"left": 12, "right": 12, "top": 12, "bottom": 6}),
                ui.Expanded(self._body_surface),
                spacing=0,
                expand=True,
            ),
            expand=True,
            class_name="gs-page-root",
        )
        return self._root_container

    def render(self, downloads: list[dict[str, Any]], *, banner: str = "") -> None:
        self._row_buttons.clear()
        self.list_column.children.clear()
        self.summary.patch(text=banner or "No active downloads")

        if not downloads:
            self.list_column.children.append(
                ui.Surface(
                    ui.Column(
                        ui.Text("Nothing downloading right now", font_size=16, font_weight="700", color=self._TEXT),
                        ui.Text(
                            "Start a pull from the Models page and it will appear here live.",
                            font_size=12,
                            color=self._MUTED,
                        ),
                        spacing=6,
                    ),
                    padding=18,
                    class_name="gs-card",
                    radius=14,
                )
            )
            self.status.patch(text="No active downloads", color=self._MUTED)
            return

        active_count = 0
        paused_count = 0
        completed_count = 0

        for item in downloads:
            download_id = str(item.get("download_id", "")).strip()
            progress = item.get("progress")
            progress_percent = item.get("progress_percent")
            done = bool(item.get("done", False))
            paused = bool(item.get("paused", False))
            error_value = item.get("error")
            error = "" if error_value in {None, "None"} else str(error_value).strip()
            status = str(item.get("status", "Queued")).strip() or "Queued"
            message = str(item.get("message", status)).strip() or status
            model = str(item.get("model", "Unknown model")).strip() or "Unknown model"

            if done and not error:
                completed_count += 1
            elif paused:
                paused_count += 1
            else:
                active_count += 1

            ring = ui.ProgressRing(
                value=progress if isinstance(progress, (int, float)) else None,
                indeterminate=not done and not paused and not isinstance(progress, (int, float)),
                stroke_width=7,
            )

            if isinstance(progress_percent, int):
                progress_text = f"Progress {progress_percent}%"
            elif paused:
                progress_text = "Paused"
            elif done and not error:
                progress_text = "Progress 100%"
            else:
                progress_text = "Waiting for progress details"

            tone = self._SUCCESS if done and not error else (self._ERROR if error else (self._ACCENT if not paused else self._MUTED))
            pause_button = ui.Button(
                text="Pause",
                class_name="gs-button gs-outline",
                variant="outlined",
                events=["click"],
                radius=10,
                disabled=done or paused,
            )
            resume_button = ui.Button(
                text="Resume",
                class_name="gs-button gs-outline",
                variant="outlined",
                events=["click"],
                radius=10,
                disabled=done or (not paused and not error),
            )
            if download_id:
                self._row_buttons[download_id] = (pause_button, resume_button)

            info_lines = [
                ui.Text(model, font_size=16, font_weight="700", color=self._TEXT),
                ui.Text(message, font_size=12, color=self._MUTED),
                ui.Text(progress_text, font_size=11, color=self._MUTED),
            ]
            if error:
                info_lines.append(ui.Text(error, font_size=11, color=self._ERROR))

            self.list_column.children.append(
                ui.Surface(
                    ui.Row(
                        ui.Container(ring, width=68, alignment="center"),
                        ui.Expanded(ui.Column(*info_lines, spacing=4)),
                        ui.Column(
                            ui.Text(status, font_size=12, color=tone, font_weight="700"),
                            ui.Row(pause_button, resume_button, spacing=8),
                            spacing=8,
                            cross_axis="end",
                        ),
                        spacing=14,
                        cross_axis="center",
                    ),
                    padding=16,
                    class_name="gs-card",
                    radius=14,
                )
            )

        self.status.patch(text=f"Active {active_count} | Paused {paused_count} | Completed {completed_count}", color=self._MUTED)
        self._bind_row_events()

    def set_status(self, text: str, *, error: bool = False, success: bool = False) -> None:
        color = self._MUTED
        if error:
            color = self._ERROR
        elif success:
            color = self._SUCCESS
        self.status.patch(text=text.strip() or "Downloads idle", color=color)

    def set_glass_mode(self, enabled: bool) -> None:
        self._glass_mode = bool(enabled)

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
            self.summary.patch(color=self._MUTED)
        except Exception:
            pass

    def set_accent(self, color: str) -> None:
        self._ACCENT = str(color or "").strip() or self._ACCENT

    def _bind_row_events(self) -> None:
        if self._bound_session is None:
            return
        for download_id, buttons in self._row_buttons.items():
            pause_button, resume_button = buttons
            pause_button.on_click(self._bound_session, lambda _event=None, target=download_id: self._emit_pause(target))
            resume_button.on_click(self._bound_session, lambda _event=None, target=download_id: self._emit_resume(target))

    def _handle_refresh(self, _event=None) -> None:
        if callable(self._on_refresh):
            self._on_refresh()

    def _emit_pause(self, download_id: str) -> None:
        if callable(self._on_pause):
            self._on_pause(download_id)

    def _emit_resume(self, download_id: str) -> None:
        if callable(self._on_resume):
            self._on_resume(download_id)
