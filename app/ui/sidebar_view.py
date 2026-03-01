from __future__ import annotations

from typing import Callable, List, Optional

import butterflyui as ui


class SidebarView:
    """A simple sidebar implemented with ButterflyUI components only.

    Usage:
        view = SidebarView(conversations=[{"id": "1", "title": "Chat A"}])
        container = view.build()
        view.on_select(lambda id: print('selected', id))
        view.on_new(lambda: print('new convo'))
    """

    def __init__(self, conversations: Optional[List[dict]] = None, width: int = 300) -> None:
        self.conversations = conversations or []
        self._on_select: Optional[Callable[[str], None]] = None
        self._on_new: Optional[Callable[[], None]] = None
        self.width = width
        self._container = self._build_container()

    def _build_container(self) -> ui.Container:
        header = ui.Container(
            ui.Row(
                ui.Text("Conversations", style={"font_size": 16}),
                ui.Spacer(),
                ui.Button(text="+", width=36, on_click=self._handle_new),
            ),
            padding=8,
        )

        self._list_col = ui.Column(spacing=6)
        for conv in self.conversations:
            self._list_col.children.append(self._conv_item(conv))

        body = ui.Expanded(child=ui.Container(self._list_col, padding=6))

        return ui.Container(ui.Column(header, body, spacing=8), width=self.width)

    def _conv_item(self, conv: dict) -> ui.Container:
        title = conv.get("title") or conv.get("name") or "Untitled"
        conv_id = conv.get("id") or title

        def _on_click(event=None, _id=conv_id):
            self._select(_id)

        btn = ui.Button(text=title, variant="text", on_click=_on_click, width="100%")
        return ui.Container(btn, padding=4)

    def _select(self, conv_id: str) -> None:
        if callable(self._on_select):
            try:
                self._on_select(conv_id)
            except Exception:
                pass

    def _handle_new(self, event=None) -> None:
        if callable(self._on_new):
            try:
                self._on_new()
            except Exception:
                pass

    def on_select(self, callback: Callable[[str], None]) -> None:
        self._on_select = callback

    def on_new(self, callback: Callable[[], None]) -> None:
        self._on_new = callback

    def set_conversations(self, conversations: List[dict]) -> None:
        self.conversations = conversations
        # rebuild list
        self._list_col.children.clear()
        for conv in self.conversations:
            self._list_col.children.append(self._conv_item(conv))

    def build(self) -> ui.Container:
        return self._container
