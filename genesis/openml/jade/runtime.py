"""Jade runtime load path for Bonzai/OpenML config activation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..versions import OPENML_VERSION
from .pack import (
    build_default_v0_files,
    build_default_v0_manifest,
    read_jadepack,
    verify_jadepack_detailed,
    write_jadepack,
)


def _parse_version(version: str) -> tuple[int, ...]:
    segments: list[int] = []
    for raw in version.strip().split("."):
        digits = ""
        for char in raw:
            if char.isdigit():
                digits += char
            else:
                break
        if digits == "":
            segments.append(0)
        else:
            segments.append(int(digits))
    return tuple(segments)


def _version_lt(left: str, right: str) -> bool:
    return _parse_version(left) < _parse_version(right)


def default_jadepack_path(data_root: str | Path = "data/openml") -> Path:
    return Path(data_root) / "jade" / "default_v0.jadepack"


def ensure_default_jadepack(path: str | Path) -> Path:
    """Create a default runtime jadepack if it does not already exist."""

    pack_path = Path(path)
    if pack_path.exists():
        return pack_path

    files = build_default_v0_files()
    manifest = build_default_v0_manifest(files)
    write_jadepack(pack_path, manifest, files)
    return pack_path


def load_runtime_jadepack(
    *,
    path: str | Path | None = None,
    data_root: str | Path = "data/openml",
    auto_create: bool = True,
    min_openml_version: str = OPENML_VERSION,
) -> dict[str, Any]:
    """Load rules/config from a verified jadepack for runtime activation."""

    pack_path = Path(path) if path is not None else default_jadepack_path(data_root)

    if auto_create:
        ensure_default_jadepack(pack_path)
    elif not pack_path.exists():
        raise FileNotFoundError(f"Jadepack not found: {pack_path}")

    report = verify_jadepack_detailed(pack_path)
    if not report.get("ok", False):
        raise ValueError(f"Jadepack verification failed: {report.get('errors', [])}")

    manifest, read_entry = read_jadepack(pack_path)
    compat = manifest.get("compat", {}) if isinstance(manifest.get("compat"), dict) else {}

    manifest_min_openml = str(compat.get("min_openml_version", "0.0.0"))
    if _version_lt(OPENML_VERSION, manifest_min_openml):
        raise ValueError(
            "Current OpenML version is below manifest minimum: "
            f"{OPENML_VERSION} < {manifest_min_openml}"
        )

    if _version_lt(OPENML_VERSION, min_openml_version):
        raise ValueError(
            f"Current OpenML version {OPENML_VERSION} is below required minimum {min_openml_version}"
        )

    rules = json.loads(read_entry("rules/bonzai_rules.json").decode("utf-8"))
    config = json.loads(read_entry("config/openml_config.json").decode("utf-8"))

    return {
        "path": str(pack_path),
        "manifest": manifest,
        "rules": rules,
        "config": config,
        "verification": report,
    }
