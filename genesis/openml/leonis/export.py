"""Leonis dataset export pipeline and Bonzai handoff metadata."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..versions import OPENML_VERSION
from .dataset import DATASET_SCHEMA_VERSION


def _default_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _flatten_for_csv(row: dict[str, Any]) -> dict[str, Any]:
    flat = dict(row)
    flat["recent_tools_histogram"] = _stable_json(
        row.get("recent_tools_histogram", {})
        if isinstance(row.get("recent_tools_histogram"), dict)
        else {}
    )
    return flat


def export_tool_selection_dataset(
    rows: list[dict[str, Any]],
    *,
    output_dir: str | Path = "data/openml/datasets",
    timestamp: str | None = None,
    include_csv: bool = False,
    feature_version: str = "1",
) -> dict[str, str]:
    """Export stable JSONL and optional CSV + metadata for Leonis outputs."""

    ts = timestamp or _default_timestamp()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    base_name = f"tool_select_{ts}"
    jsonl_path = out_dir / f"{base_name}.jsonl"

    ordered_rows = sorted(rows, key=lambda row: (int(row.get("created_at", 0)), str(row.get("trace_id", ""))))

    with jsonl_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in ordered_rows:
            handle.write(_stable_json(row))
            handle.write("\n")

    outputs = {"jsonl": str(jsonl_path)}

    if include_csv:
        csv_path = out_dir / f"{base_name}.csv"
        if ordered_rows:
            fieldnames = sorted(ordered_rows[0].keys())
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for row in ordered_rows:
                    writer.writerow(_flatten_for_csv(row))
        else:
            csv_path.write_text("", encoding="utf-8")
        outputs["csv"] = str(csv_path)

    metadata = {
        "type": "leonis_tool_selection_dataset",
        "schema_version": DATASET_SCHEMA_VERSION,
        "feature_version": feature_version,
        "openml_version": OPENML_VERSION,
        "row_count": len(ordered_rows),
        "created_at": datetime.now(UTC).isoformat(),
        "compat": {
            "bonzai": {
                "minimum_feature_version": feature_version,
                "supported_labels": ["tool", "ask_user", "final_answer"],
            },
            "model_targets": ["lightgbm", "xgboost"],
        },
    }

    metadata_path = out_dir / f"{base_name}.meta.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs["metadata"] = str(metadata_path)

    return outputs
