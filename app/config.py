from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AppPaths:
	root: Path
	app_root: Path
	data_root: Path
	templates_root: Path
	static_root: Path
	terminal_payload: Path
	settings_file: Path


@dataclass(frozen=True)
class RuntimeSettings:
	host: str = "127.0.0.1"
	preferred_port: int = 9988
	max_port_scan: int = 12
	db_path: str = "data/genesis.sqlite"
	ollama_base_url: str = "http://127.0.0.1:11434"
	model: str = "qwen2.5-coder:7b"
	request_timeout: float = 120.0
	ollama_models_dir: str = "models/ollama"
	ollama_auto_pull: bool = True
	preferred_shell: str = "auto"


def resolve_paths() -> AppPaths:
	app_root = Path(__file__).resolve().parent
	root = app_root.parent
	data_root = app_root / "data"
	templates_root = app_root / "html"
	static_root = app_root / "static"
	terminal_payload = data_root / "terminal_payload.json"
	settings_file = root / "data" / "settings.json"

	return AppPaths(
		root=root,
		app_root=app_root,
		data_root=data_root,
		templates_root=templates_root,
		static_root=static_root,
		terminal_payload=terminal_payload,
		settings_file=settings_file,
	)


def load_runtime_settings(settings_file: Path) -> RuntimeSettings:
	settings_payload: dict[str, Any] = {}
	try:
		if settings_file.exists():
			parsed = json.loads(settings_file.read_text(encoding="utf-8"))
			if isinstance(parsed, dict):
				settings_payload = parsed
	except Exception:
		settings_payload = {}

	runtime = settings_payload.get("runtime", {})
	if not isinstance(runtime, dict):
		runtime = {}

	def _int(name: str, fallback: int) -> int:
		try:
			return int(runtime.get(name, fallback))
		except Exception:
			return fallback

	def _float(name: str, fallback: float) -> float:
		try:
			return float(runtime.get(name, fallback))
		except Exception:
			return fallback

	def _str(name: str, fallback: str) -> str:
		value = runtime.get(name, fallback)
		return str(value).strip() or fallback

	def _bool(name: str, fallback: bool) -> bool:
		value = runtime.get(name, fallback)
		if isinstance(value, bool):
			return value
		raw = str(value).strip().lower()
		if raw in {"1", "true", "yes", "on"}:
			return True
		if raw in {"0", "false", "no", "off"}:
			return False
		return bool(fallback)

	host = os.environ.get("GENESIS_RUNTIME_HOST", _str("host", "127.0.0.1"))
	preferred_port = _int("preferred_port", 9988)
	max_port_scan = _int("max_port_scan", 12)
	db_path = _str("db_path", "data/genesis.sqlite")
	ollama_base_url = os.environ.get("GENESIS_OLLAMA_BASE_URL", _str("ollama_base_url", "http://127.0.0.1:11434"))
	model = os.environ.get("GENESIS_MODEL", _str("model", "qwen2.5-coder:7b"))
	request_timeout = _float("request_timeout", 120.0)
	ollama_models_dir = os.environ.get("GENESIS_OLLAMA_MODELS_DIR", _str("ollama_models_dir", "models/ollama"))
	ollama_auto_pull = _bool("ollama_auto_pull", True)
	env_auto_pull = os.environ.get("GENESIS_OLLAMA_AUTO_PULL")
	if env_auto_pull is not None:
		ollama_auto_pull = str(env_auto_pull).strip().lower() in {"1", "true", "yes", "on"}
	preferred_shell = _str("preferred_shell", "")
	if not preferred_shell:
		preferred_shell = os.environ.get("GENESIS_SHELL", "auto")
	preferred_shell = str(preferred_shell).strip() or "auto"

	return RuntimeSettings(
		host=host,
		preferred_port=max(1, preferred_port),
		max_port_scan=max(1, max_port_scan),
		db_path=db_path,
		ollama_base_url=ollama_base_url.rstrip("/"),
		model=model,
		request_timeout=max(5.0, request_timeout),
		ollama_models_dir=ollama_models_dir,
		ollama_auto_pull=ollama_auto_pull,
		preferred_shell=preferred_shell,
	)
