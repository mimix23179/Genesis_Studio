from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def json_for_script_tag(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False)
    return raw.replace("</", "<\\/")


def render_template(template: str, replacements: dict[str, str]) -> str:
    output = template
    for key, value in replacements.items():
        output = output.replace(key, value)
    return output


def escape_html(value: str) -> str:
    return html.escape(value, quote=True)
