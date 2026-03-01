from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_text_file(path: Path) -> str:
	return path.read_text(encoding="utf-8")


def read_json_file(path: Path, default: Any = None) -> Any:
	if not path.exists():
		return {} if default is None else default
	with path.open("r", encoding="utf-8") as file:
		return json.load(file)


def json_for_script_tag(payload: Any) -> str:
	text = json.dumps(payload, ensure_ascii=False)
	return text.replace("</", "<\\/")
