from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import butterflyui as ui

from app.utils import read_text_file, json_for_script_tag


class TerminalContainer:
    """Builds an HtmlView for the terminal drawer using the packaged HTML template.

    The view exposes `open()` and `close()` helpers which send control postMessage
    payloads to the page. The host can also send `output` messages to feed data
    to the terminal.
    """

    def __init__(self, paths: Any) -> None:
        self.paths = paths
        # Corrected template name to terminal.html
        self.template_path = paths.templates_root / "terminal.html"
        self.static_root = paths.static_root
        self.view: Optional[ui.HtmlView] = None

    def build(self) -> ui.HtmlView:
        tpl = read_text_file(self.template_path)
        
        # Load CSS and JS for injection
        css_content = read_text_file(self.static_root / "css" / "terminal.css")
        js_content = read_text_file(self.static_root / "js" / "terminal.js")
        
        # include a small payload object for initial config
        payload = json_for_script_tag({"welcome": "Genesis Shell — ready"})
        
        # Inject contents
        html = tpl.replace("__COMPONENT_CSS__", css_content)
        html = html.replace("__COMPONENT_JS__", js_content)
        html = html.replace("</body>", f"<script>window.__TERMINAL_PAYLOAD__ = {payload};</script></body>")
        
        self.view = ui.HtmlView(html=html, expand=True, events=["message"], style={"background": "transparent"})
        return self.view

    def open(self, session: Any) -> None:
        if self.view is None:
            return
        try:
            self.view.invoke(session, "postMessage", {"payload": {"type": "control", "action": "open"}})
        except Exception:
            pass

    def close(self, session: Any) -> None:
        if self.view is None:
            return
        try:
            self.view.invoke(session, "postMessage", {"payload": {"type": "control", "action": "close"}})
        except Exception:
            pass

    def send_output(self, session: Any, data: str) -> None:
        if self.view is None:
            return
        try:
            self.view.invoke(session, "postMessage", {"payload": {"type": "output", "data": data}})
        except Exception:
            pass
