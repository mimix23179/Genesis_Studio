from __future__ import annotations

import html
import re
from typing import Any

import butterflyui as ui


class ChatPage:
    """Stable chat workspace built from reliable ButterflyUI primitives."""

    _BG = "#F7F7F8"
    _THREAD_BG = "#FFFFFF"
    _SURFACE = "#FFFFFF"
    _BORDER = "#D1D5DB"
    _TEXT = "#111827"
    _MUTED = "#6B7280"
    _ACCENT = "#10A37F"
    _USER_BG = "#E8F5E9"
    _ASSIST_BG = "#FFFFFF"
    _ON_ACCENT = "#FFFFFF"
    _INPUT_BG = "#FFFFFF"
    _STATUS_ERROR = "#B91C1C"
    _STATUS_BUSY = "#1D4ED8"
    _STATUS_READY = "#047857"

    def __init__(self) -> None:
        self._glass_mode = False
        self._root_container: ui.Container | None = None
        self._header_surface: ui.Surface | None = None
        self._thread_container: ui.Container | None = None
        self._composer_surface: ui.Surface | None = None
        self._message_shadow = [{"color": "#220F172A", "blur": 18, "spread": 1, "offset_x": 0, "offset_y": 6}]
        self._streaming_controls: dict[str, ui.Text] = {}

        # Header
        self.title = ui.Text(
            "Genesis",
            font_size=22,
            font_weight="700",
            color=self._TEXT,
        )
        self.subtitle = ui.Text(
            "Self-contained local runtime",
            font_size=12,
            color=self._MUTED,
        )
        self.runtime_label = ui.Text(
            "Runtime: Ollama",
            font_size=12,
            font_weight="600",
            color=self._ACCENT,
        )

        # Thread
        self.chat_list = ui.ScrollableColumn(
            spacing=10,
            content_padding={"left": 12, "right": 12, "top": 12, "bottom": 12},
            expand=True,
        )
        self.typing_indicator = ui.Text(
            "Genesis is typing...",
            visible=False,
            font_size=12,
            color=self._MUTED,
            italic=True,
        )
        self._messages: list[dict[str, Any]] = []
        self._streaming_text: dict[str, str] = {}
        self._streaming_widgets: dict[str, int] = {}

        # Composer
        self._composer_value: str = ""
        self.composer = ui.TextField(
            placeholder="Message Genesis...",
            class_name="gs-input",
            events=["change", "submit"],
            font_size=14,
            radius=10,
            dense=False,
            expand=True,
        )
        self.send_button = ui.Button(
            text="Send",
            class_name="gs-button gs-primary",
            variant="filled",
            events=["click"],
            radius=10,
            font_weight="700",
        )

        # Context + status
        self.context_switch = ui.Switch(
            value=True,
            label="Genesis source context",
            inline=True,
            events=["change"],
        )
        self.context_info = ui.Text(
            "Context: ready",
            font_size=12,
            color=self._MUTED,
        )
        self.status_text = ui.Text(
            "Idle",
            font_size=12,
            color=self._MUTED,
        )

    def build(self):
        self._header_surface = ui.Surface(
            ui.Row(
                ui.Column(self.title, self.subtitle, spacing=2),
                ui.Spacer(),
                self.runtime_label,
                spacing=8,
            ),
            padding=14,
            class_name="gs-page-header",
        )

        self._thread_container = ui.Surface(
            ui.Column(self.chat_list, self.typing_indicator, spacing=6, expand=True),
            expand=True,
            class_name="gs-panel",
            radius=12,
        )
        messages = ui.Expanded(child=self._thread_container)

        context_row = ui.Container(
            ui.Row(self.context_switch, ui.Spacer(), self.context_info, spacing=8),
            padding={"left": 12, "right": 12, "top": 6, "bottom": 2},
        )

        self._composer_surface = ui.Surface(
            ui.Row(self.composer, self.send_button, spacing=10, cross_axis="end"),
            padding=10,
            class_name="gs-panel",
            radius=12,
        )

        status_row = ui.Container(
            ui.Row(self.status_text, ui.Spacer()),
            padding={"left": 12, "right": 12, "top": 2, "bottom": 6},
        )

        layout = ui.Column(
            ui.Container(self._header_surface, padding={"left": 12, "right": 12, "top": 12, "bottom": 4}),
            messages,
            context_row,
            ui.Container(self._composer_surface, padding={"left": 12, "right": 12, "top": 2, "bottom": 2}),
            status_row,
            spacing=0,
            expand=True,
        )
        self._root_container = ui.Container(layout, expand=True, class_name="gs-page-root")
        return self._root_container

    def _extract_event_text(self, event: Any) -> str:
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

    def on_composer_change(self, event: Any = None) -> None:
        value = self._extract_event_text(event)
        self._composer_value = value

    def get_composer_text(self) -> str:
        return self._composer_value.strip()

    def clear_composer(self) -> None:
        self._composer_value = ""
        try:
            self.composer.patch(value="", text="", data="")
        except Exception:
            pass

    def set_title(self, title: str) -> None:
        if title.strip():
            self.title.patch(text=title)

    def set_runtime_label(self, text: str) -> None:
        label = text.strip() or "Runtime: Ollama"
        self.runtime_label.patch(text=label)

    def set_status(self, status: str) -> None:
        label = status.strip() or "Idle"
        color = self._MUTED
        lowered = label.lower()
        if "error" in lowered or "fail" in lowered:
            color = self._STATUS_ERROR
        elif "stream" in lowered or "wait" in lowered or "load" in lowered:
            color = self._STATUS_BUSY
        elif "ready" in lowered or "connected" in lowered:
            color = self._STATUS_READY
        self.status_text.patch(text=label, color=color)

    def set_context_info(self, text: str) -> None:
        self.context_info.patch(text=text.strip() or "Context: ready")

    def use_genesis_context(self) -> bool:
        try:
            props = self.context_switch.to_dict().get("props", {})
            return bool(props.get("value", False))
        except Exception:
            return True

    def _message_row(self, message: dict[str, Any]) -> ui.Row:
        text = str(message.get("text", ""))
        role = str(message.get("role", "assistant"))
        message_id = str(message.get("id", "")).strip()
        is_user = role == "user"
        render_mode = str(message.get("render_mode", "markdown" if role == "assistant" else "text")).strip().lower()
        label = ui.Text(
            "You" if is_user else "Genesis",
            font_size=11,
            font_weight="700",
            color=self._ACCENT if is_user else self._MUTED,
        )
        if not is_user and render_mode == "markdown" and text.strip():
            body = self._assistant_rich_body(text)
        else:
            body = self._streaming_controls.get(message_id) if message_id else None
            if body is None:
                body = ui.Text(
                    text,
                    font_size=14,
                    color=self._TEXT,
                    selectable=True,
                )
                if message_id:
                    self._streaming_controls[message_id] = body
            else:
                try:
                    body.patch(text=text, color=self._TEXT)
                except Exception:
                    pass
        bubble = ui.Container(
            ui.Surface(
                ui.Column(label, body, spacing=6),
                padding={"left": 14, "right": 14, "top": 12, "bottom": 12},
                class_name="gs-message-user" if is_user else "gs-message-assistant",
                radius=18,
            ),
            class_name="gs-message-user" if is_user else "gs-message-assistant",
            width="82%",
        )
        if is_user:
            return ui.Row(ui.Spacer(), bubble)
        return ui.Row(bubble, ui.Spacer())

    def _assistant_rich_body(self, text: str):
        blocks = self._split_markdown_blocks(text)
        controls: list[Any] = []
        for block_type, payload in blocks:
            if block_type == "table" and isinstance(payload, dict):
                controls.append(self._render_markdown_table(payload))
            elif block_type == "markdown":
                chunk = str(payload or "").strip()
                if chunk:
                    controls.append(
                        ui.MarkdownView(
                            value=chunk,
                            selectable=True,
                            scrollable=False,
                            render_mode="markdown",
                        )
                    )
        if not controls:
            return ui.Text(text, font_size=14, color=self._TEXT, selectable=True)
        if len(controls) == 1:
            return ui.Container(controls[0], width="100%")
        return ui.Container(ui.Column(*controls, spacing=10), width="100%")

    def _render_markdown_table(self, table_data: dict[str, Any]):
        raw_columns = [str(item) for item in table_data.get("columns", [])]
        alignments = [str(item) for item in table_data.get("alignments", [])]
        columns = []
        for index, item in enumerate(raw_columns):
            alignment = alignments[index] if index < len(alignments) else "left"
            columns.append(
                {
                    "id": f"col_{index}",
                    "label": self._normalize_table_cell(item),
                    "numeric": alignment in {"right", "center"} and self._looks_numeric_column(table_data.get("rows", []), index),
                }
            )
        rows = []
        for row in table_data.get("rows", []):
            values = [self._normalize_table_cell(str(cell)) for cell in row]
            rows.append({f"col_{index}": values[index] if index < len(values) else "" for index in range(len(columns))})
        if not columns:
            return ui.Text("", font_size=14, color=self._TEXT)
        return ui.Container(
            ui.DataTable(
                columns=columns,
                rows=rows,
                sortable=False,
                filterable=False,
                selectable=False,
                dense=True,
                striped=True,
                show_header=True,
            ),
            width="100%",
        )

    def _split_markdown_blocks(self, text: str) -> list[tuple[str, Any]]:
        lines = str(text or "").splitlines()
        blocks: list[tuple[str, Any]] = []
        markdown_buffer: list[str] = []
        index = 0
        in_fence = False

        while index < len(lines):
            line = lines[index]
            if self._is_fence_marker(line):
                in_fence = not in_fence
                markdown_buffer.append(line)
                index += 1
                continue

            if not in_fence and self._is_table_header(lines, index):
                if markdown_buffer:
                    chunk = "\n".join(markdown_buffer).strip()
                    if chunk:
                        blocks.append(("markdown", chunk))
                    markdown_buffer = []
                table_lines = [lines[index], lines[index + 1]]
                index += 2
                while index < len(lines) and self._looks_like_table_row(lines[index]):
                    table_lines.append(lines[index])
                    index += 1
                parsed = self._parse_markdown_table(table_lines)
                if parsed is not None:
                    blocks.append(("table", parsed))
                else:
                    markdown_buffer.extend(table_lines)
                continue
            markdown_buffer.append(line)
            index += 1

        if markdown_buffer:
            chunk = "\n".join(markdown_buffer).strip()
            if chunk:
                blocks.append(("markdown", chunk))
        return blocks

    def _is_table_header(self, lines: list[str], index: int) -> bool:
        if index + 1 >= len(lines):
            return False
        return self._looks_like_table_row(lines[index]) and self._looks_like_table_separator(lines[index + 1])

    @staticmethod
    def _looks_like_table_row(line: str) -> bool:
        raw = str(line or "").strip()
        return raw.count("|") >= 2 and not raw.startswith("```")

    @staticmethod
    def _looks_like_table_separator(line: str) -> bool:
        raw = str(line or "").strip()
        if raw.count("|") < 2:
            return False
        cells = [cell.strip() for cell in raw.strip("|").split("|")]
        if not cells:
            return False
        return all(bool(re.fullmatch(r":?-{3,}:?", cell)) for cell in cells)

    def _parse_markdown_table(self, lines: list[str]) -> dict[str, Any] | None:
        if len(lines) < 2:
            return None
        headers = self._split_table_cells(lines[0])
        separator = self._split_table_cells(lines[1])
        if not headers or len(headers) != len(separator):
            return None
        alignments = [self._separator_alignment(cell) for cell in separator]
        rows: list[list[str]] = []
        for line in lines[2:]:
            values = self._split_table_cells(line)
            if not values:
                continue
            if len(values) < len(headers):
                values.extend([""] * (len(headers) - len(values)))
            rows.append(values[: len(headers)])
        return {"columns": headers, "rows": rows, "alignments": alignments}

    @staticmethod
    def _split_table_cells(line: str) -> list[str]:
        raw = str(line or "").strip()
        if not raw:
            return []
        if raw.startswith("|"):
            raw = raw[1:]
        if raw.endswith("|"):
            raw = raw[:-1]
        return [cell.strip() for cell in raw.split("|")]

    @staticmethod
    def _is_fence_marker(line: str) -> bool:
        return str(line or "").strip().startswith("```")

    @staticmethod
    def _separator_alignment(cell: str) -> str:
        value = str(cell or "").strip()
        if value.startswith(":") and value.endswith(":"):
            return "center"
        if value.endswith(":"):
            return "right"
        return "left"

    @staticmethod
    def _normalize_table_cell(value: str) -> str:
        text = html.unescape(str(value or "").strip())
        text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
        text = re.sub(r"(?<!\*)\*(?!\*)([^*]+)(?<!\*)\*(?!\*)", r"\1", text)
        text = re.sub(r"(?<!_)_(?!_)([^_]+)(?<!_)_(?!_)", r"\1", text)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        return text.strip()

    @staticmethod
    def _looks_numeric_column(rows: list[list[str]] | Any, index: int) -> bool:
        if not isinstance(rows, list) or not rows:
            return False
        checked = 0
        numeric = 0
        for row in rows:
            if not isinstance(row, list) or index >= len(row):
                continue
            value = str(row[index] or "").strip()
            if not value:
                continue
            checked += 1
            normalized = value.replace(",", "").replace("$", "").replace("%", "")
            if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", normalized):
                numeric += 1
        return checked > 0 and numeric == checked

    def _sync_thread(self, session=None) -> None:
        rows = [
            self._message_row(msg)
            for msg in self._messages
        ]
        self.chat_list.children.clear()
        self.chat_list.children.extend(rows)
        try:
            if session is not None:
                self.chat_list.patch(session=session, children=self.chat_list.children)
        except Exception:
            pass

    def clear_messages(self, session=None) -> None:
        self._messages.clear()
        self._sync_thread(session)
        self._streaming_text.clear()
        self._streaming_widgets.clear()
        self._streaming_controls.clear()
        self.typing_indicator.patch(visible=False)

    def get_messages_snapshot(self) -> list[dict[str, Any]]:
        return [dict(message) for message in self._messages]

    def restore_messages_snapshot(self, messages: list[dict[str, Any]] | None, session=None) -> None:
        self._messages = []
        for message in (messages or []):
            item = dict(message)
            role = str(item.get("role", "assistant"))
            if role == "assistant":
                item["render_mode"] = str(item.get("render_mode", "markdown"))
            else:
                item["render_mode"] = str(item.get("render_mode", "text"))
            self._messages.append(item)
        self._streaming_text.clear()
        self._streaming_widgets.clear()
        self._streaming_controls.clear()
        self.typing_indicator.patch(visible=False)
        self._sync_thread(session)

    def add_user_message(self, text: str, session=None) -> None:
        self._messages.append({"text": text, "role": "user", "render_mode": "text"})
        self._sync_thread(session)

    def add_assistant_message(self, text: str, session=None) -> None:
        self._messages.append({"text": text, "role": "assistant", "render_mode": "markdown"})
        self._sync_thread(session)

    def begin_streaming(self, message_id: str, session=None) -> None:
        if message_id in self._streaming_widgets:
            return
        self._messages.append({"id": message_id, "text": "", "role": "assistant", "render_mode": "text"})
        self._streaming_widgets[message_id] = len(self._messages) - 1
        self._streaming_text[message_id] = ""
        self._sync_thread(session)
        self.typing_indicator.patch(visible=True)
        self.set_status("Streaming response...")

    def add_delta(self, message_id: str, delta: str, session=None) -> None:
        if message_id not in self._streaming_text:
            return
        self._streaming_text[message_id] += delta or ""
        message_index = self._streaming_widgets.get(message_id)
        if isinstance(message_index, int) and 0 <= message_index < len(self._messages):
            self._messages[message_index]["text"] = self._streaming_text[message_id]
            body = self._streaming_controls.get(message_id)
            if body is not None:
                try:
                    body.patch(text=self._streaming_text[message_id])
                except Exception:
                    self._sync_thread(session)
            else:
                self._sync_thread(session)

    def finalize_stream(self, message_id: str, full_text: str, session=None) -> None:
        self._streaming_text.pop(message_id, None)
        message_index = self._streaming_widgets.pop(message_id, None)
        self._streaming_controls.pop(message_id, None)
        if isinstance(message_index, int) and 0 <= message_index < len(self._messages):
            self._messages[message_index]["text"] = full_text
            self._messages[message_index]["render_mode"] = "markdown"
            self._sync_thread(session)
        else:
            self.add_assistant_message(full_text, session)
        self.typing_indicator.patch(visible=len(self._streaming_widgets) > 0)
        self.set_status("Idle")

    def set_glass_mode(self, enabled: bool) -> None:
        self._glass_mode = bool(enabled)

    def set_palette(self, palette: dict[str, str], session=None) -> None:
        self._BG = palette.get("bg", self._BG)
        self._THREAD_BG = palette.get("thread_bg", self._THREAD_BG)
        self._SURFACE = palette.get("surface", self._SURFACE)
        self._BORDER = palette.get("border", self._BORDER)
        self._TEXT = palette.get("text", self._TEXT)
        self._MUTED = palette.get("muted", self._MUTED)
        self._ACCENT = palette.get("accent", self._ACCENT)
        self._USER_BG = palette.get("user_bg", self._USER_BG)
        self._ASSIST_BG = palette.get("assist_bg", self._ASSIST_BG)
        self._ON_ACCENT = palette.get("on_accent", self._ON_ACCENT)
        self._INPUT_BG = palette.get("input_bg", self._INPUT_BG)
        self._message_shadow = [{"color": palette.get("glow", "#220F172A"), "blur": 18, "spread": 1, "offset_x": 0, "offset_y": 6}]

        try:
            self.title.patch(color=self._TEXT)
            self.subtitle.patch(color=self._MUTED)
            self.runtime_label.patch(color=self._ACCENT)
            self.context_info.patch(color=self._MUTED)
            self.typing_indicator.patch(color=self._MUTED)
        except Exception:
            pass

        self._sync_thread(session)

    def set_accent(self, color: str) -> None:
        accent = str(color or "").strip() or self._ACCENT
        self._ACCENT = accent
        try:
            self.runtime_label.patch(color=accent)
        except Exception:
            pass
