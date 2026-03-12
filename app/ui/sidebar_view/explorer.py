from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

import butterflyui as ui


class ExplorerSidebar:
    """Workspace explorer sidebar for the IDE view."""

    _BG = "#F7F7F8"
    _SURFACE = "#FFFFFF"
    _BORDER = "#E5E7EB"
    _TEXT = "#0F172A"
    _MUTED = "#475569"
    _ACCENT = "#10A37F"
    _ACTIVE_BG = "#DCE6FF"
    _ACTIVE_TEXT = "#0B1220"

    def __init__(self, width: int = 280) -> None:
        self.width = width
        self._glass_mode = False
        self._root_container: ui.Container | None = None
        self._outline_host: ui.Container | None = None
        self._bound_session: Any = None
        self._on_refresh: Optional[Callable[[], None]] = None
        self._on_select_file: Optional[Callable[[str], None]] = None
        self._root_path = Path.cwd()
        self._selected_path = ""
        self._expanded_dirs: set[str] = set()
        self._query = ""
        self._max_nodes = 400
        self._last_nodes: list[dict[str, Any]] = []

        self.title = ui.Text("Explorer", font_size=16, font_weight="700", color=self._TEXT)
        self.subtitle = ui.Text("Workspace files", font_size=11, color=self._MUTED)
        self.root_label = ui.Text(str(self._root_path), font_size=11, color=self._MUTED)
        self.summary_label = ui.Text("0 items", font_size=11, color=self._MUTED)
        self.refresh_button = ui.GlyphButton(
            glyph="refresh",
            tooltip="Refresh explorer",
            events=["click"],
            color=self._TEXT,
            size="20",
        )
        self.search_field = ui.TextField(
            value="",
            class_name="gs-input",
            placeholder="Search files",
            events=["change", "submit"],
        )
        self.outline = ui.Outline(
            nodes=[],
            class_name="gs-outline",
            expanded=[],
            selected_id=None,
            dense=True,
            show_icons=True,
            events=["select", "expand"],
            expand=True,
        )

    def on_refresh(self, callback: Callable[[], None]) -> None:
        self._on_refresh = callback

    def on_select_file(self, callback: Callable[[str], None]) -> None:
        self._on_select_file = callback

    def bind_events(self, session) -> None:
        self._bound_session = session
        self.refresh_button.on_click(session, self._handle_refresh)
        self.search_field.on_change(session, self._handle_search_change)
        self.search_field.on_submit(session, self._handle_search_change)
        self.outline.on_select(session, self._handle_outline_select)
        self.outline.on_event(session, "expand", self._handle_outline_expand)

    def set_root(self, root: str | Path, *, selected_path: str | Path | None = None) -> None:
        candidate = Path(root).resolve()
        self._root_path = candidate
        self.root_label.patch(text=str(candidate))
        self._expanded_dirs.add(str(candidate))
        if selected_path is not None:
            self._selected_path = str(Path(selected_path).resolve())
            self._expand_to_selected(Path(self._selected_path))
        self._rebuild_outline()

    def build(self) -> ui.Container:
        header = ui.Container(
            ui.Column(
                ui.Row(self.title, ui.Spacer(), self.refresh_button, spacing=8, cross_axis="center"),
                self.subtitle,
                self.root_label,
                ui.Container(self.search_field, padding={"top": 6, "bottom": 2}),
                self.summary_label,
                spacing=4,
            ),
            padding={"left": 16, "right": 12, "top": 16, "bottom": 8},
        )
        self._outline_host = ui.Container(
            ui.Container(self.outline, expand=True, padding={"left": 8, "right": 8, "top": 4, "bottom": 12}),
            expand=True,
        )
        self._rebuild_outline()
        self._root_container = ui.Container(
            ui.Column(header, ui.Expanded(self._outline_host), spacing=0, expand=True),
            width=self.width,
            class_name="gs-sidebar",
            style={"border_right": f"1px solid {self._BORDER}"},
        )
        return self._root_container

    def set_glass_mode(self, enabled: bool) -> None:
        self._glass_mode = bool(enabled)
        self._rebuild_outline()

    def set_palette(self, palette: dict[str, str]) -> None:
        self._BG = palette.get("bg", self._BG)
        self._SURFACE = palette.get("surface", self._SURFACE)
        self._BORDER = palette.get("border", self._BORDER)
        self._TEXT = palette.get("text", self._TEXT)
        self._MUTED = palette.get("muted", self._MUTED)
        self._ACCENT = palette.get("accent", self._ACCENT)
        self._ACTIVE_BG = palette.get("active_bg", self._ACTIVE_BG)
        self._ACTIVE_TEXT = palette.get("active_text", self._ACTIVE_TEXT)
        try:
            self.title.patch(color=self._TEXT)
            self.subtitle.patch(color=self._MUTED)
            self.root_label.patch(color=self._MUTED)
            self.summary_label.patch(color=self._MUTED)
            self.refresh_button.patch(color=self._TEXT)
            self.outline.patch(selected_id=self._selected_path or None)
        except Exception:
            pass
        self._rebuild_outline()

    def _rebuild_outline(self) -> None:
        if not self._root_path.exists():
            self.summary_label.patch(text="Workspace root unavailable")
            self._last_nodes = []
            self.outline.patch(nodes=[], expanded=[], selected_id=None)
            return
        nodes, count = self._build_directory_nodes(self._root_path, depth=0, root=True)
        self._last_nodes = nodes
        self.summary_label.patch(text=f"{count} items" if not self._query else f"{count} matches")
        self.outline.patch(
            nodes=nodes,
            expanded=sorted(self._expanded_dirs),
            selected_id=self._selected_path or None,
        )

    def _build_directory_nodes(self, directory: Path, *, depth: int, root: bool = False) -> tuple[list[dict[str, Any]], int]:
        if depth > 18:
            return [], 0
        directory_key = str(directory.resolve())
        query = self._query.strip().lower()
        expanded = root or bool(query) or directory_key in self._expanded_dirs
        children: list[dict[str, Any]] = []
        count = 0
        try:
            entries = sorted(directory.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        except Exception:
            entries = []
        for entry in entries:
            if count >= self._max_nodes:
                break
            if self._should_skip(entry):
                continue
            if entry.is_dir():
                child_nodes, child_count = self._build_directory_nodes(entry, depth=depth + 1)
                if child_nodes or self._matches_query(entry):
                    node = {
                        "id": str(entry.resolve()),
                        "label": entry.name,
                        "icon": "folder",
                        "children": child_nodes,
                    }
                    children.append(node)
                    count += 1 + child_count
            else:
                if query and not self._matches_query(entry):
                    continue
                children.append(
                    {
                        "id": str(entry.resolve()),
                        "label": entry.name,
                        "icon": self._icon_for_file(entry),
                    }
                )
                count += 1
        if not root and query and not children and not self._matches_query(directory):
            return [], 0
        node = {
            "id": directory_key,
            "label": directory.name or str(directory),
            "icon": "folder",
            "children": children,
        }
        if root:
            return [node], min(count + 1, self._max_nodes)
        return [node], min(count + 1, self._max_nodes)

    def _handle_outline_select(self, event=None) -> None:
        path_key = self._extract_value(event)
        if not path_key:
            return
        candidate = Path(path_key)
        if candidate.exists() and candidate.is_dir():
            self._toggle_directory(path_key)
            return
        self._selected_path = str(candidate.resolve())
        self._expand_to_selected(candidate.resolve())
        self._rebuild_outline()
        if callable(self._on_select_file):
            self._on_select_file(self._selected_path)

    def _handle_outline_expand(self, event=None) -> None:
        payload = self._extract_payload(event)
        if isinstance(payload.get("expanded"), list):
            self._expanded_dirs = {str(item) for item in payload.get("expanded", []) if item}
            self._expanded_dirs.add(str(self._root_path.resolve()))
            return
        path_key = str(payload.get("id") or payload.get("selected_id") or payload.get("value") or "").strip()
        if not path_key:
            return
        expanded = payload.get("isExpanded", payload.get("expanded", None))
        if expanded is None:
            self._toggle_directory(path_key)
            return
        if bool(expanded):
            self._expanded_dirs.add(path_key)
        else:
            self._expanded_dirs.discard(path_key)
        self._expanded_dirs.add(str(self._root_path.resolve()))
        self._rebuild_outline()

    def _handle_search_change(self, value=None, event=None) -> None:
        candidate = ""
        if isinstance(value, str):
            candidate = value
        elif value is not None:
            candidate = str(value)
        if not candidate:
            candidate = self._extract_value(event)
        self._query = candidate.strip()
        if self._query and self._selected_path:
            self._expand_to_selected(Path(self._selected_path))
        self._rebuild_outline()

    def _handle_refresh(self, _event=None) -> None:
        self._rebuild_outline()
        if callable(self._on_refresh):
            self._on_refresh()

    def _toggle_directory(self, path_key: str) -> None:
        normalized = str(Path(path_key).resolve())
        if normalized in self._expanded_dirs:
            self._expanded_dirs.remove(normalized)
        else:
            self._expanded_dirs.add(normalized)
        self._expanded_dirs.add(str(self._root_path.resolve()))
        self._rebuild_outline()

    def _expand_to_selected(self, path: Path) -> None:
        resolved = path.resolve()
        for parent in [resolved, *resolved.parents]:
            self._expanded_dirs.add(str(parent.resolve()))
            if parent.resolve() == self._root_path.resolve():
                break

    def _matches_query(self, path: Path) -> bool:
        query = self._query.strip().lower()
        if not query:
            return True
        name = path.name.lower()
        if query in name:
            return True
        try:
            relative = str(path.resolve().relative_to(self._root_path.resolve())).replace("\\", "/").lower()
        except Exception:
            relative = str(path).replace("\\", "/").lower()
        return query in relative

    def _icon_for_file(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".py", ".js", ".ts", ".html", ".css", ".sh", ".ps1"}:
            return "code"
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}:
            return "image"
        return "description"

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
    def _extract_value(cls, event: Any) -> str:
        payload = cls._extract_payload(event)
        for key in ("selected_id", "id", "value", "text", "label", "data"):
            value = payload.get(key)
            if value is not None:
                return str(value)
        if isinstance(event, str):
            return event
        return ""

    def _should_skip(self, path: Path) -> bool:
        name = path.name.lower()
        if name in {".git", "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules", "env"}:
            return True
        raw = str(path).replace("\\", "/").lower()
        if "/site-packages/" in raw or "/models/ollama/blobs/" in raw:
            return True
        return False
