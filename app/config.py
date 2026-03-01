from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
	root: Path
	app_root: Path
	data_root: Path
	templates_root: Path
	static_root: Path
	terminal_payload: Path


@dataclass(frozen=True)
class RuntimeSettings:
	host: str = "127.0.0.1"
	preferred_port: int = 9988
	max_port_scan: int = 12
	db_path: str = "data/genesis.sqlite"


def resolve_paths() -> AppPaths:
	app_root = Path(__file__).resolve().parent
	root = app_root.parent
	data_root = app_root / "data"
	templates_root = app_root / "html"
	static_root = app_root / "static"
	terminal_payload = data_root / "terminal_payload.json"

	return AppPaths(
		root=root,
		app_root=app_root,
		data_root=data_root,
		templates_root=templates_root,
		static_root=static_root,
		terminal_payload=terminal_payload,
	)
