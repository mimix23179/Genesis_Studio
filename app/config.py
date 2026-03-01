from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class PathsConfig:
    project_root: Path
    templates_root: Path
    static_root: Path
    models_root: Path
    conversations_root: Path


def resolve_paths() -> PathsConfig:
    base = Path.cwd()
    return PathsConfig(
        project_root=base,
        templates_root=base / "app" / "html",
        static_root=base / "app" / "static",
        models_root=base / "models",
        conversations_root=base / "data" / "conversations",
    )
