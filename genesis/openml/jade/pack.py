"""Jadepack write/read/verify APIs."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Callable

from .codecs import canonical_json_bytes, normalize_pack_path, sha256_bytes
from .manifest import JadeManifest, build_manifest, validate_manifest


def _normalize_files(files: dict[str, bytes]) -> dict[str, bytes]:
    normalized: dict[str, bytes] = {}
    for path, payload in files.items():
        clean_path = normalize_pack_path(path)
        if not isinstance(payload, bytes):
            raise TypeError(f"Pack payload for {clean_path} must be bytes")
        normalized[clean_path] = payload
    return normalized


def write_jadepack(path: str | Path, manifest: dict[str, Any], files: dict[str, bytes]) -> None:
    """Write a `.jadepack` ZIP with strict manifest/file consistency checks."""

    pack_path = Path(path)
    pack_path.parent.mkdir(parents=True, exist_ok=True)

    normalized_files = _normalize_files(files)
    validated_manifest = validate_manifest(manifest)

    manifest_paths = {entry.path for entry in validated_manifest.contents}
    file_paths = set(normalized_files.keys())

    missing_payloads = sorted(manifest_paths.difference(file_paths))
    if missing_payloads:
        raise ValueError(f"Manifest paths missing payload bytes: {missing_payloads}")

    extra_payloads = sorted(file_paths.difference(manifest_paths))
    if extra_payloads:
        raise ValueError(f"Payload includes paths not present in manifest: {extra_payloads}")

    for entry in validated_manifest.contents:
        payload = normalized_files[entry.path]
        computed_hash = sha256_bytes(payload)
        if computed_hash != entry.sha256:
            raise ValueError(f"sha256 mismatch for {entry.path}")
        if len(payload) != entry.size_bytes:
            raise ValueError(f"size_bytes mismatch for {entry.path}")

    with zipfile.ZipFile(pack_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(validated_manifest.model_dump(mode="json"), ensure_ascii=False, indent=2))
        for file_path in sorted(normalized_files.keys()):
            archive.writestr(file_path, normalized_files[file_path])


def read_jadepack(path: str | Path) -> tuple[dict[str, Any], Callable[[str], bytes]]:
    """Read a jadepack and return `(manifest, file_reader)` with no side effects."""

    pack_path = Path(path)
    with zipfile.ZipFile(pack_path, mode="r") as archive:
        raw_manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        validated = validate_manifest(raw_manifest)

        payloads: dict[str, bytes] = {}
        for entry in validated.contents:
            payloads[entry.path] = archive.read(entry.path)

    def read_entry(entry_path: str) -> bytes:
        normalized = normalize_pack_path(entry_path)
        if normalized not in payloads:
            raise KeyError(f"Entry not found in jadepack: {normalized}")
        return payloads[normalized]

    return validated.model_dump(mode="json"), read_entry


def verify_jadepack_detailed(path: str | Path) -> dict[str, Any]:
    """Verify manifest integrity and per-entry hashes/sizes."""

    errors: list[str] = []

    try:
        manifest, read_entry = read_jadepack(path)
        validated = JadeManifest.model_validate(manifest)
    except Exception as exc:
        return {"ok": False, "errors": [f"read_failed: {exc}"]}

    for entry in validated.contents:
        try:
            payload = read_entry(entry.path)
        except Exception as exc:
            errors.append(f"missing_entry:{entry.path}:{exc}")
            continue

        digest = sha256_bytes(payload)
        if digest != entry.sha256:
            errors.append(f"hash_mismatch:{entry.path}")
        if len(payload) != entry.size_bytes:
            errors.append(f"size_mismatch:{entry.path}")

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "entry_count": len(validated.contents),
    }


def verify_jadepack(path: str | Path) -> bool:
    """Return `True` only when manifest and file hashes are valid."""

    report = verify_jadepack_detailed(path)
    return bool(report.get("ok", False))


def build_default_v0_files(
    *,
    bonzai_rules: dict[str, Any] | None = None,
    openml_config: dict[str, Any] | None = None,
) -> dict[str, bytes]:
    """Build required v0 content payloads for a default jadepack."""

    rules_payload = bonzai_rules or {
        "version": "0",
        "mode": "rules-first",
        "ordered_intents": ["workspace-missing", "repeated-failure", "debug", "search", "edit", "fallback"],
    }
    config_payload = openml_config or {
        "tool_timeout_ms": 120000,
        "trace_required": True,
        "offline_only": True,
    }

    return {
        "rules/bonzai_rules.json": canonical_json_bytes(rules_payload),
        "config/openml_config.json": canonical_json_bytes(config_payload),
        "models/.keep": b"",
    }


def build_default_v0_manifest(files: dict[str, bytes]) -> dict[str, Any]:
    """Build a strict default v0 manifest from content files."""

    return build_manifest(
        files,
        compat={
            "min_genesis_version": "0.1.0",
        },
    )
