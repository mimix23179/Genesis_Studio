"""Jadepack manifest contracts and validation."""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..versions import JADE_FORMAT_VERSION, OPENML_VERSION
from .codecs import normalize_pack_path, sha256_bytes

_REQUIRED_CONTENT_PATHS = {"rules/bonzai_rules.json", "config/openml_config.json"}


class ManifestEntry(BaseModel):
    """One content entry in a Jadepack manifest."""

    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return normalize_pack_path(value)

    @field_validator("sha256")
    @classmethod
    def _validate_sha256(cls, value: str) -> str:
        normalized = value.lower().strip()
        if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return normalized


class ManifestCompat(BaseModel):
    """Compatibility constraints for runtime activation."""

    model_config = ConfigDict(extra="allow")

    min_genesis_version: str | None = None
    min_openml_version: str | None = None


class JadeManifest(BaseModel):
    """Strict manifest contract for Jadepack containers."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["jadepack"]
    format_version: int = Field(ge=1)
    created_at: int = Field(ge=0)
    openml_version: str
    contents: list[ManifestEntry]
    compat: ManifestCompat

    @field_validator("format_version")
    @classmethod
    def _validate_format_version(cls, value: int) -> int:
        if value != JADE_FORMAT_VERSION:
            raise ValueError(
                f"Unsupported format_version: {value}; expected {JADE_FORMAT_VERSION}"
            )
        return value

    @field_validator("contents")
    @classmethod
    def _validate_contents(cls, value: list[ManifestEntry]) -> list[ManifestEntry]:
        if not value:
            raise ValueError("Manifest contents cannot be empty")

        paths = {entry.path for entry in value}
        missing = sorted(_REQUIRED_CONTENT_PATHS.difference(paths))
        if missing:
            raise ValueError(f"Manifest missing required content paths: {missing}")
        return value


def validate_manifest(manifest: dict[str, Any]) -> JadeManifest:
    """Validate a raw manifest dictionary."""

    return JadeManifest.model_validate(manifest)


def build_manifest(
    files: dict[str, bytes],
    *,
    created_at: int | None = None,
    compat: dict[str, Any] | None = None,
    openml_version: str = OPENML_VERSION,
) -> dict[str, Any]:
    """Build a strict Jade manifest from a path->bytes mapping."""

    normalized_files: dict[str, bytes] = {}
    for path, payload in files.items():
        normalized = normalize_pack_path(path)
        normalized_files[normalized] = payload

    now = int(time.time()) if created_at is None else int(created_at)
    entries = [
        {
            "path": path,
            "sha256": sha256_bytes(payload),
            "size_bytes": len(payload),
        }
        for path, payload in sorted(normalized_files.items())
    ]

    manifest = {
        "format": "jadepack",
        "format_version": JADE_FORMAT_VERSION,
        "created_at": now,
        "openml_version": openml_version,
        "contents": entries,
        "compat": {
            "min_openml_version": openml_version,
            **(compat or {}),
        },
    }

    validated = validate_manifest(manifest)
    return validated.model_dump(mode="json")
