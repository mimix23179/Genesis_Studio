"""Helpers for Jadepack encoding and hashing."""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalize_pack_path(path: str) -> str:
    normalized = str(PurePosixPath(path))
    if normalized.startswith("/"):
        raise ValueError(f"Pack paths must be relative: {path}")
    if normalized in {"", "."}:
        raise ValueError("Pack path must be non-empty")
    if ".." in PurePosixPath(normalized).parts:
        raise ValueError(f"Pack path cannot escape pack root: {path}")
    return normalized


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
