from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable

import butterflyui as ui


class IDEPage:
    """Native ButterflyUI IDE page with gutter and minimap-style preview."""

    _BG = "#F6F8FC"
    _SURFACE = "#FFFFFF"
    _SURFACE_ALT = "#F8FAFC"
    _BORDER = "#D6DEE8"
    _TEXT = "#0F172A"
    _MUTED = "#64748B"
    _ACCENT = "#10A37F"
    _ON_ACCENT = "#FFFFFF"
    _SUCCESS = "#047857"
    _ERROR = "#B91C1C"
    _LINE_HEIGHT = 20
    _MINIMAP_WINDOW = 42

    def __init__(self) -> None:
        self._bound_session: Any = None
        self._root_container: ui.Container | None = None
        self._tab_surface: ui.Surface | None = None
        self._editor_surface: ui.Surface | None = None
        self._glass_mode = False
        self._workspace_root = Path.cwd()
        self._current_file: Path | None = None
        self._open_tabs: list[Path] = []
        self._tab_buttons: dict[str, ui.Button] = {}
        self._on_save: Callable[[], None] | None = None
        self._dirty_files: dict[str, bool] = {}
        self._last_save_serial = 0
        self._saved_text = ""
        self._current_text = ""

        self.file_label = ui.Text("No file selected", font_size=13, font_weight="700", color=self._TEXT)
        self.status = ui.Text("IDE idle", font_size=11, color=self._MUTED)
        self.language_label = ui.Text("PLAIN TEXT", font_size=11, color=self._MUTED)
        self.metrics_label = ui.Text("0 lines | 0 chars", font_size=11, color=self._MUTED)

        self.save_button = ui.Button(
            text="Save",
            class_name="gs-button gs-primary",
            variant="filled",
            events=["click"],
            radius=10,
            font_weight="700",
            disabled=True,
        )
        self.reload_button = ui.Button(
            text="Reload File",
            class_name="gs-button gs-outline",
            variant="outlined",
            events=["click"],
            radius=10,
        )
        self.open_devtools_button = ui.Button(
            text="Preview",
            class_name="gs-button gs-outline",
            variant="outlined",
            events=["click"],
            radius=10,
        )

        self.editor_input = ui.TextArea(
            value="Select a file from the Explorer sidebar to start.",
            class_name="gs-editor",
            min_lines=32,
            max_lines=32,
            emit_on_change=True,
            debounce_ms=0,
            placeholder="Open a file to begin editing",
            events=["change", "submit", "key_down"],
            radius=0,
            content_padding={"left": 12, "right": 12, "top": 12, "bottom": 18},
            style={"fontFamily": "Consolas, Cascadia Code, Courier New, monospace", "fontSize": "13px", "lineHeight": f"{self._LINE_HEIGHT}px"},
        )

        # Gutter and minimap are rendered as columns of small interactive items
        self.gutter_column = ui.Column(spacing=0)
        self._gutter_buttons: list[ui.Button] = []
        self.minimap_column = ui.Column(spacing=0)
        self._minimap_buttons: list[ui.Button] = []
        self._highlighted_line: int | None = None
        self.minimap_window = ui.Container(
            height=96,
            radius=999,
            bgcolor="#2010A37F",
            border_color="#5510A37F",
            border_width=1,
        )
        self.tabs_row = ui.Row(spacing=8, cross_axis="center")

    def on_save(self, callback: Callable[[], None]) -> None:
        self._on_save = callback

    def bind_events(self, session) -> None:
        self._bound_session = session
        self.save_button.on_click(session, self._handle_save)
        self.reload_button.on_click(session, self._handle_reload)
        self.open_devtools_button.on_click(session, self._handle_preview_focus)
        self.editor_input.on_change(session, self._handle_editor_change)
        self.editor_input.on_submit(session, self._handle_editor_submit)
        self.editor_input.on_key_down(session, self._handle_editor_key_down)
        self._bind_tab_events()
        # Attach any gutter/minimap handlers for the current session
        self._attach_gutter_minimap_events()

    def build(self) -> ui.Container:
        tab_row = ui.Row(
            ui.Expanded(self.tabs_row),
            self.save_button,
            self.reload_button,
            self.open_devtools_button,
            spacing=10,
            cross_axis="center",
        )
        self._tab_surface = ui.Surface(
            ui.Container(tab_row, padding={"left": 8, "right": 8, "top": 8, "bottom": 8}),
            class_name="gs-card",
            radius=14,
        )

        self._gutter_container = ui.Container(
            self.gutter_column,
            width=58,
            padding={"left": 0, "right": 8, "top": 12, "bottom": 18},
            style={"borderRight": f"1px solid {self._BORDER}"},
        )
        editor = ui.Container(self.editor_input, expand=True)
        self._minimap_container = ui.Container(
            ui.Column(
                ui.Expanded(ui.Container(self.minimap_column, padding={"left": 8, "right": 8, "top": 12, "bottom": 8})),
                ui.Container(self.minimap_window, padding={"left": 8, "right": 8, "top": 0, "bottom": 12}),
                spacing=0,
                expand=True,
            ),
            width=96,
            style={"borderLeft": f"1px solid {self._BORDER}"},
        )
        editor_row = ui.Row(self._gutter_container, ui.Expanded(editor), self._minimap_container, spacing=0, expand=True)

        self._editor_surface = ui.Surface(
            ui.Column(
                self.file_label,
                ui.Row(self.status, self.language_label, self.metrics_label, spacing=12, cross_axis="center"),
                ui.Expanded(ui.Container(editor_row, padding={"top": 10}, expand=True)),
                spacing=4,
                expand=True,
            ),
            padding={"left": 12, "right": 0, "top": 10, "bottom": 0},
            class_name="gs-card",
            radius=14,
        )
        self._root_container = ui.Container(
            ui.Column(
                ui.Container(self._tab_surface, padding={"left": 12, "right": 12, "top": 12, "bottom": 6}),
                ui.Expanded(ui.Container(self._editor_surface, padding={"left": 12, "right": 12, "top": 0, "bottom": 12})),
                spacing=0,
                expand=True,
            ),
            expand=True,
            class_name="gs-page-root",
        )
        self._refresh_editor_chrome()
        self._rebuild_tabs()
        return self._root_container

    def set_workspace_root(self, root: str | Path) -> None:
        self._workspace_root = Path(root).resolve()

    def open_file(self, path: str | Path) -> None:
        target = Path(path).resolve()
        if not target.exists() or not target.is_file():
            self.status.patch(text=f"File unavailable: {target}", color=self._ERROR)
            return
        self._current_file = target
        self._open_tabs = [item for item in self._open_tabs if item != target]
        self._open_tabs.insert(0, target)
        self._open_tabs = self._open_tabs[:8]
        self._render_current_file(success_message=f"Opened {self._format_relative(target)}")

    def current_file_path(self) -> str:
        return str(self._current_file.resolve()) if self._current_file is not None else ""

    def is_dirty(self) -> bool:
        current = self.current_file_path()
        return bool(current and self._dirty_files.get(current, False))

    def set_palette(self, palette: dict[str, str]) -> None:
        self._BG = palette.get("bg", self._BG)
        self._SURFACE = palette.get("surface", self._SURFACE)
        self._SURFACE_ALT = palette.get("surface_alt", self._SURFACE_ALT)
        self._BORDER = palette.get("border", self._BORDER)
        self._TEXT = palette.get("text", self._TEXT)
        self._MUTED = palette.get("muted", self._MUTED)
        self._ACCENT = palette.get("accent", self._ACCENT)
        self._ON_ACCENT = palette.get("on_accent", self._ON_ACCENT)
        self._refresh_theme()
        if self._current_file is not None:
            self._refresh_editor_chrome()
        self._rebuild_tabs()

    def set_glass_mode(self, enabled: bool) -> None:
        self._glass_mode = bool(enabled)
        self._rebuild_tabs()

    async def capture_editor_state_async(self) -> dict[str, Any] | None:
        text = self._current_text
        line_count = len(text.splitlines()) if text else 1
        return {
            "label": self.file_label.to_dict().get("props", {}).get("value", "") if hasattr(self.file_label, "to_dict") else self.current_file_path(),
            "language": self.language_label.to_dict().get("props", {}).get("value", "") if hasattr(self.language_label, "to_dict") else "plaintext",
            "text": text,
            "lineCount": line_count,
            "charCount": len(text),
            "dirty": text != self._saved_text,
            "saveSerial": self._last_save_serial,
        }

    def apply_runtime_state(self, snapshot: dict[str, Any]) -> None:
        if self._current_file is None or not isinstance(snapshot, dict):
            return
        dirty = bool(snapshot.get("dirty", False))
        current_key = self.current_file_path()
        self._dirty_files[current_key] = dirty
        line_count = int(snapshot.get("lineCount", 0) or 0)
        char_count = int(snapshot.get("charCount", 0) or 0)
        if line_count > 0 or char_count > 0:
            self.metrics_label.patch(text=f"{line_count} lines | {char_count} chars")
        self.status.patch(text="Unsaved changes" if dirty else f"Editing {self._format_relative(self._current_file)}", color=self._ACCENT if dirty else self._MUTED)
        self.save_button.patch(disabled=not dirty)
        self._rebuild_tabs()

    def mark_saved(self, text: str) -> None:
        if self._current_file is None:
            return
        current_key = self.current_file_path()
        self._saved_text = text
        self._current_text = text
        self._dirty_files[current_key] = False
        self.save_button.patch(disabled=True)
        self.status.patch(text=f"Saved {self._format_relative(self._current_file)}", color=self._SUCCESS)
        # Use a safe setter that avoids synchronous invoke() calls while the runtime loop is active.
        try:
            self._set_editor_value(text)
        except Exception:
            try:
                self.editor_input.patch(value=text)
            except Exception:
                pass
        self._refresh_editor_chrome()
        self._rebuild_tabs()

    def next_save_serial(self) -> int:
        return self._last_save_serial

    def set_status(self, text: str, *, error: bool = False, success: bool = False) -> None:
        color = self._MUTED
        if error:
            color = self._ERROR
        elif success:
            color = self._SUCCESS
        self.status.patch(text=text.strip() or "IDE idle", color=color)

    def _handle_save(self, _event=None) -> None:
        self._last_save_serial += 1
        if callable(self._on_save):
            self._on_save()

    def _handle_reload(self, _event=None) -> None:
        if self._current_file is None:
            self.status.patch(text="Select a file before reloading.", color=self._MUTED)
            return
        self._render_current_file(success_message=f"Reloaded {self._format_relative(self._current_file)}")

    def _handle_preview_focus(self, _event=None) -> None:
        self.set_status(f"Previewing {self._format_relative(self._current_file) if self._current_file else 'editor'}")

    def _handle_editor_submit(self, value=None, event=None) -> None:
        self._sync_editor_value(value, event)

    def _handle_editor_change(self, value=None, event=None) -> None:
        self._sync_editor_value(value, event)

    def _handle_editor_key_down(self, _value=None, event=None) -> None:
        payload = self._extract_payload(event)
        key = str(payload.get("key", payload.get("value", ""))).lower()
        ctrl = bool(payload.get("ctrlKey") or payload.get("control") or payload.get("ctrl"))
        meta = bool(payload.get("metaKey") or payload.get("meta"))
        if key == "s" and (ctrl or meta):
            self._last_save_serial += 1
            if callable(self._on_save):
                self._on_save()
        # Update highlighted line if possible
        try:
            candidate = self._extract_cursor_line(event)
            if candidate is not None:
                self._highlight_line(int(candidate))
        except Exception:
            pass

    def _sync_editor_value(self, value=None, event=None) -> None:
        candidate = self._extract_text_value(value, event)
        if candidate is None:
            return
        self._current_text = candidate
        current_key = self.current_file_path()
        if current_key:
            is_dirty = candidate != self._saved_text
            self._dirty_files[current_key] = is_dirty
            self.save_button.patch(disabled=not is_dirty)
            self.status.patch(text="Unsaved changes" if is_dirty else f"Editing {self._format_relative(self._current_file)}", color=self._ACCENT if is_dirty else self._MUTED)
        self._refresh_editor_chrome()
        self._rebuild_tabs()
        # Attempt to highlight current line from event payload
        try:
            candidate_line = self._extract_cursor_line(event)
            if candidate_line is not None:
                self._highlight_line(int(candidate_line))
        except Exception:
            pass

    def _rebuild_tabs(self) -> None:
        self.tabs_row.children.clear()
        self._tab_buttons.clear()
        if not self._open_tabs:
            self.tabs_row.children.append(ui.Text("No open tabs yet", font_size=11, color=self._MUTED))
            return
        for tab_path in self._open_tabs:
            key = str(tab_path.resolve())
            is_active = self._current_file == tab_path
            is_dirty = self._dirty_files.get(key, False)
            display_label = self._format_relative(tab_path) if is_active else tab_path.name
            label = f"* {display_label}" if is_dirty else display_label
            button = ui.Button(
                text=label,
                class_name="gs-button gs-tab-active" if is_active else "gs-button gs-tab",
                variant="filled" if is_active else "outlined",
                events=["click"],
                radius=10,
                font_weight="700" if is_active else "600",
            )
            self._tab_buttons[key] = button
            self.tabs_row.children.append(button)
        self._bind_tab_events()

    def _bind_tab_events(self) -> None:
        if self._bound_session is None:
            return
        for key, button in self._tab_buttons.items():
            button.on_click(self._bound_session, lambda _event=None, target=key: self.open_file(target))

    def _attach_gutter_minimap_events(self) -> None:
        # Attach click handlers for any existing gutter/minimap buttons when a session is bound
        if self._bound_session is None:
            return
        try:
            for idx, btn in enumerate(getattr(self, "_gutter_buttons", []), start=1):
                btn.on_click(self._bound_session, lambda _event=None, target=idx: self._jump_to_line(target))
        except Exception:
            pass
        try:
            lines_all = self._current_text.splitlines() or [""]
            mini_lines = self._build_minimap_lines(self._current_text)
            for idx, btn in enumerate(getattr(self, "_minimap_buttons", []), start=1):
                if mini_lines and mini_lines[-1] == "..." and idx == len(mini_lines):
                    target = len(lines_all)
                else:
                    target = idx
                btn.on_click(self._bound_session, lambda _event=None, target_line=target: self._jump_to_line(target_line))
        except Exception:
            pass

    def _jump_to_line(self, line: int) -> None:
        # Best-effort: attempt to move cursor / scroll to the target line. If not supported,
        # update status so user sees intended action.
        try:
            self.set_status(f"Jumping to line {line}")
            # Try a few likely APIs; swallow failures gracefully.
            try:
                # Some controls support a patch of cursor/selection information
                self.editor_input.patch(cursor_line=line)
            except Exception:
                pass
            try:
                # TextArea may expose a convenience setter; attempt to call it with a cursor payload
                if self._bound_session is not None:
                    try:
                        # Prefer patching the selection prop (no invoke) so we avoid invoke() warnings.
                        self.editor_input.patch(session=self._bound_session, selection={"startLine": line, "startColumn": 0, "endLine": line, "endColumn": 0})
                        # Try to focus the control asynchronously to bring it into view.
                        try:
                            self._bound_session.spawn(lambda: self.editor_input.invoke_async(self._bound_session, "request_focus", {}))
                        except Exception:
                            pass
                    except Exception:
                        # fallback: try patching selection prop locally
                        try:
                            self.editor_input.patch(selection={"startLine": line, "startColumn": 0})
                        except Exception:
                            pass
            except Exception:
                pass
        except Exception:
            pass

    def _render_current_file(self, *, success_message: str) -> None:
        if self._current_file is None:
            return
        try:
            text = self._current_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = self._current_file.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            self.status.patch(text=f"Open failed: {exc}", color=self._ERROR)
            return

        relative_label = self._format_relative(self._current_file)
        language = self._language_for_file(self._current_file)
        line_count = len(text.splitlines()) or 1
        char_count = len(text)
        self._saved_text = text
        self._current_text = text
        self._dirty_files[self.current_file_path()] = False
        self.file_label.patch(text=relative_label)
        self.language_label.patch(text=language.upper())
        self.metrics_label.patch(text=f"{line_count} lines | {char_count} chars")
        self.save_button.patch(disabled=True)
        self.status.patch(text=success_message, color=self._SUCCESS)
        try:
            self._set_editor_value(text)
        except Exception:
            try:
                self.editor_input.patch(value=text)
            except Exception:
                pass
        self._refresh_editor_chrome()
        self._rebuild_tabs()

    def _refresh_theme(self) -> None:
        input_bg = self._SURFACE_ALT
        border = self._SURFACE_ALT
        text = self._TEXT
        muted = self._MUTED
        try:
            self.file_label.patch(color=text)
            self.language_label.patch(color=muted)
            self.metrics_label.patch(color=muted)
            self.minimap_window.patch(bgcolor=self._alpha(self._ACCENT, 0.14), border_color=self._alpha(self._ACCENT, 0.35))
        except Exception:
            pass

    def _refresh_editor_chrome(self) -> None:
        line_count = max(1, len(self._current_text.splitlines()) if self._current_text else 1)
        # Rebuild gutter as individual clickable items (best-effort)
        try:
            self._gutter_buttons.clear()
            if hasattr(self, "gutter_column"):
                self.gutter_column.children.clear()
            for i in range(1, line_count + 1):
                btn = ui.Button(
                    text=str(i),
                    class_name="gs-editor-line",
                    events=["click"],
                    radius=0,
                    font_size=12,
                    font_family="Consolas, Cascadia Code, Courier New, monospace",
                )
                self._gutter_buttons.append(btn)
                if hasattr(self, "gutter_column"):
                    self.gutter_column.children.append(btn)
            if self._bound_session is not None:
                for idx, btn in enumerate(self._gutter_buttons, start=1):
                    btn.on_click(self._bound_session, lambda _event=None, target=idx: self._jump_to_line(target))
        except Exception:
            pass

        # Rebuild minimap preview as individual clickable items
        mini_lines = self._build_minimap_lines(self._current_text)
        try:
            self._minimap_buttons.clear()
            if hasattr(self, "minimap_column"):
                self.minimap_column.children.clear()
            all_lines = self._current_text.splitlines() or [""]
            for idx, raw in enumerate(mini_lines, start=1):
                display = raw
                btn = ui.Button(
                    text=display,
                    class_name="gs-minimap-line",
                    events=["click"],
                    radius=0,
                    font_size=7,
                    font_family="Consolas, Cascadia Code, Courier New, monospace",
                )
                self._minimap_buttons.append(btn)
                if hasattr(self, "minimap_column"):
                    self.minimap_column.children.append(btn)
            if self._bound_session is not None:
                for idx, btn in enumerate(self._minimap_buttons, start=1):
                    if mini_lines and mini_lines[-1] == "..." and idx == len(mini_lines):
                        target = len(all_lines)
                    else:
                        target = idx
                    btn.on_click(self._bound_session, lambda _event=None, target_line=target: self._jump_to_line(target_line))
        except Exception:
            pass

        viewport_height = max(56, min(180, int(math.ceil((self._MINIMAP_WINDOW / max(1, line_count)) * 420))))
        self.minimap_window.patch(height=viewport_height)
        self.metrics_label.patch(text=f"{line_count} lines | {len(self._current_text)} chars")

    def _build_minimap_lines(self, text: str) -> list[str]:
        lines = text.splitlines() or [""]
        preview: list[str] = []
        for raw in lines[:180]:
            compact = raw.replace("\t", "    ")
            if len(compact) > 34:
                compact = compact[:34]
            preview.append(compact or " ")
        if len(lines) > 180:
            preview.append("...")
        return preview

    def _read_control_value(self, control: Any, fallback: str = "") -> str:
        session = self._bound_session
        if session is not None:
            try:
                value = session.get_value(control, prop="value")
                if value is not None:
                    return str(value)
            except Exception:
                pass
        try:
            props = control.to_dict().get("props", {})
            return str(props.get("value", fallback))
        except Exception:
            return str(fallback)

    def _set_editor_value(self, value: Any) -> None:
        # Set editor value without blocking the running event loop.
        session = self._bound_session
        if session is not None:
            try:
                # Schedule an async invocation instead of calling invoke() synchronously.
                session.spawn(lambda: self.editor_input.invoke_async(session, "set_value", {"value": str(value)}))
                return
            except Exception:
                pass
        try:
            self.editor_input.patch(value=str(value))
        except Exception:
            pass

    def _extract_cursor_line(self, event: Any) -> int | None:
        payload = self._extract_payload(event)
        if not payload:
            return None
        # Common payload shapes: {'cursor': {'line': N}} or {'selection': {'startLine': N}}
        cursor = payload.get("cursor") or payload.get("caret")
        if isinstance(cursor, dict):
            for k in ("line", "row", "lineNumber", "startLine"):
                v = cursor.get(k)
                if v is not None:
                    try:
                        return int(v)
                    except Exception:
                        pass
        selection = payload.get("selection") or payload.get("sel")
        if isinstance(selection, dict):
            for k in ("startLine", "line", "row", "start"):
                v = selection.get(k)
                if v is not None:
                    try:
                        return int(v)
                    except Exception:
                        pass
        for k in ("line", "lineNumber", "row", "cursorLine", "cursor_line", "caretLine"):
            v = payload.get(k)
            if v is not None:
                try:
                    return int(v)
                except Exception:
                    pass
        return None

    def _highlight_line(self, line: int) -> None:
        # Clamp and update gutter/minimap visuals for the active line
        try:
            max_line = max(1, len(self._current_text.splitlines()) if self._current_text else 1)
            if line < 1:
                line = 1
            if line > max_line:
                line = max_line
            prev = getattr(self, "_highlighted_line", None)
            if prev == line:
                return
            # Reset previous gutter button
            try:
                if prev is not None and 1 <= prev <= len(getattr(self, "_gutter_buttons", [])):
                    prev_btn = self._gutter_buttons[prev - 1]
                    prev_btn.patch(class_name="gs-editor-line", font_weight="600")
            except Exception:
                pass
            # Highlight new gutter button
            try:
                if 1 <= line <= len(getattr(self, "_gutter_buttons", [])):
                    btn = self._gutter_buttons[line - 1]
                    btn.patch(class_name="gs-editor-line-active", font_weight="700")
            except Exception:
                pass
            # Update minimap highlight
            try:
                mini_lines = self._build_minimap_lines(self._current_text)
                # Reset all minimap buttons
                for b in getattr(self, "_minimap_buttons", []):
                    try:
                        b.patch(class_name="gs-minimap-line")
                    except Exception:
                        pass
                if mini_lines:
                    if mini_lines and mini_lines[-1] == "...":
                        idx = int((line - 1) / max_line * (len(mini_lines) - 1)) + 1
                    else:
                        idx = min(line, len(mini_lines))
                    if 1 <= idx <= len(getattr(self, "_minimap_buttons", [])):
                        try:
                            self._minimap_buttons[idx - 1].patch(class_name="gs-minimap-line-active")
                        except Exception:
                            pass
            except Exception:
                pass
            self._highlighted_line = line
        except Exception:
            pass

    def _format_relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self._workspace_root)).replace("\\", "/")
        except Exception:
            return str(path)

    @staticmethod
    def _language_for_file(path: Path) -> str:
        mapping = {
            ".py": "python",
            ".md": "markdown",
            ".json": "json",
            ".yml": "yaml",
            ".yaml": "yaml",
            ".toml": "toml",
            ".txt": "plaintext",
            ".js": "javascript",
            ".ts": "typescript",
            ".html": "html",
            ".css": "css",
            ".sh": "shell",
            ".ps1": "powershell",
        }
        return mapping.get(path.suffix.lower(), "plaintext")

    @staticmethod
    def _extract_payload(event: Any) -> dict[str, Any]:
        if isinstance(event, dict):
            payload = event.get("payload")
            if isinstance(payload, dict):
                return payload
            return event
        payload = getattr(event, "payload", None)
        return payload if isinstance(payload, dict) else {}

    @classmethod
    def _extract_text_value(cls, value: Any, event: Any) -> str | None:
        if isinstance(value, str):
            return value
        payload = cls._extract_payload(event)
        for key in ("value", "text", "data"):
            candidate = payload.get(key)
            if candidate is not None:
                return str(candidate)
        return None

    @staticmethod
    def _alpha(color: str, opacity: float) -> str:
        normalized = color.lstrip("#")
        if len(normalized) != 6:
            return color
        alpha = max(0, min(255, int(opacity * 255)))
        return f"#{alpha:02X}{normalized}"
