"""Leonis handoff preparation for future Bonzai trainable path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .dataset import build_tool_selection_dataset
from .eval import evaluate_tool_selection_dataset
from .export import export_tool_selection_dataset


def prepare_bonzai_handoff(
    *,
    store,
    workspace_id: str,
    limit_traces: int = 200,
    output_dir: str | Path = "data/openml/datasets",
    include_csv: bool = True,
    min_rows: int = 10,
    success_threshold: float = 0.6,
    feature_version: str = "1",
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Build, evaluate, and export a Leonis dataset package for Bonzai."""

    rows = build_tool_selection_dataset(store, workspace_id, limit_traces=limit_traces)
    evaluation = evaluate_tool_selection_dataset(
        rows,
        min_rows=min_rows,
        success_threshold=success_threshold,
    )
    exports = export_tool_selection_dataset(
        rows,
        output_dir=output_dir,
        timestamp=timestamp,
        include_csv=include_csv,
        feature_version=feature_version,
    )

    return {
        "rows": rows,
        "evaluation": evaluation,
        "exports": exports,
        "handoff_ready": bool(evaluation.get("passed", False)),
    }
