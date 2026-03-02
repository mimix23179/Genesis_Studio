"""Leonis dataset contracts and builder for tool-selection training rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..abyss.store import AbyssStore

DATASET_SCHEMA_VERSION = "1"

FEATURE_FIELDS = (
    "intent_category",
    "recent_failures_count",
    "recent_successes_count",
    "has_git",
    "dirty_repo",
    "file_count",
    "recent_tools_histogram",
    "avg_tool_duration_ms",
    "last_error_type",
    "last_exit_code",
)


@dataclass(slots=True)
class ToolSelectionSchema:
    """Schema contract for Leonis tool-selection rows."""

    schema_version: str = DATASET_SCHEMA_VERSION
    feature_fields: tuple[str, ...] = FEATURE_FIELDS
    label_field: str = "chosen_tool"
    outcome_field: str = "success"


def tool_selection_schema() -> ToolSelectionSchema:
    return ToolSelectionSchema()


def _extract_decision_payload(trace_payload: dict[str, Any]) -> dict[str, Any]:
    events = trace_payload.get("events", [])
    for event in events:
        if event.get("type") == "decision":
            data = event.get("data")
            if isinstance(data, dict):
                return data
    return {}


def _extract_duration_ms(trace_payload: dict[str, Any], fallback: float) -> float:
    durations: list[float] = []
    for event in trace_payload.get("events", []):
        if event.get("type") == "tool.result":
            data = event.get("data", {})
            value = data.get("duration_ms")
            try:
                if value is not None:
                    durations.append(float(value))
            except (TypeError, ValueError):
                continue

    if durations:
        return float(sum(durations) / len(durations))
    return float(fallback)


def _coerce_histogram(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}

    histogram: dict[str, int] = {}
    for key in sorted(value.keys()):
        k = str(key)
        try:
            histogram[k] = int(value[key])
        except (TypeError, ValueError):
            continue
    return histogram


def _normalize_tool_label(decision: dict[str, Any]) -> str:
    action_type = str(decision.get("action_type") or "")
    tool = decision.get("tool")
    if isinstance(tool, str) and tool.strip():
        return tool
    if action_type in {"ask_user", "final_answer"}:
        return action_type
    return ""


def validate_tool_selection_row(row: dict[str, Any]) -> None:
    """Validate row structure against Leonis L0 schema contract."""

    schema = tool_selection_schema()

    if row.get("schema_version") != schema.schema_version:
        raise ValueError("Invalid schema_version in dataset row")

    for field in schema.feature_fields:
        if field not in row:
            raise ValueError(f"Missing feature field: {field}")

    intent_category = row["intent_category"]
    if intent_category not in {"debug", "search", "edit", "run", "other"}:
        raise ValueError(f"Invalid intent_category: {intent_category}")

    int_fields = (
        "recent_failures_count",
        "recent_successes_count",
        "has_git",
        "dirty_repo",
        "file_count",
        "last_exit_code",
        "success",
    )
    for field in int_fields:
        if not isinstance(row[field], int):
            raise ValueError(f"Field must be int: {field}")

    if row["has_git"] not in {0, 1}:
        raise ValueError("has_git must be 0 or 1")
    if row["dirty_repo"] not in {0, 1}:
        raise ValueError("dirty_repo must be 0 or 1")
    if row["success"] not in {0, 1}:
        raise ValueError("success must be 0 or 1")

    if not isinstance(row["recent_tools_histogram"], dict):
        raise ValueError("recent_tools_histogram must be a dict")
    if not isinstance(row["avg_tool_duration_ms"], float):
        raise ValueError("avg_tool_duration_ms must be float")
    if not isinstance(row["last_error_type"], str):
        raise ValueError("last_error_type must be str")
    if not isinstance(row["chosen_tool"], str) or not row["chosen_tool"]:
        raise ValueError("chosen_tool must be a non-empty str")


def build_tool_selection_dataset(
    store: AbyssStore,
    workspace_id: str,
    limit_traces: int = 200,
) -> list[dict[str, Any]]:
    """Build Leonis dataset rows from Abyss traces for one workspace."""

    if limit_traces <= 0:
        raise ValueError("limit_traces must be positive")

    recent = store.list_recent_traces(workspace_id, limit=limit_traces)
    ordered = sorted(recent, key=lambda trace: (trace.created_at, trace.trace_id))

    file_count = len(store.list_documents(workspace_id))
    rows: list[dict[str, Any]] = []

    for summary in ordered:
        trace_payload = store.load_trace(summary.trace_id)
        if not trace_payload:
            continue

        decision = _extract_decision_payload(trace_payload)
        features = decision.get("features") if isinstance(decision, dict) else None
        features = features if isinstance(features, dict) else {}

        outcome = trace_payload.get("outcome")
        outcome = outcome if isinstance(outcome, dict) else {}

        row = {
            "schema_version": DATASET_SCHEMA_VERSION,
            "trace_id": summary.trace_id,
            "workspace_id": summary.workspace_id,
            "session_id": summary.session_id,
            "created_at": int(summary.created_at),
            "intent_category": str(features.get("intent_category", "other")),
            "recent_failures_count": int(features.get("recent_failures_count", 0)),
            "recent_successes_count": int(features.get("recent_successes_count", 0)),
            "has_git": int(features.get("has_git", 0)),
            "dirty_repo": int(features.get("dirty_repo", 0)),
            "file_count": int(features.get("file_count", file_count)),
            "recent_tools_histogram": _coerce_histogram(features.get("recent_tools_histogram", {})),
            "avg_tool_duration_ms": _extract_duration_ms(
                trace_payload,
                fallback=float(features.get("avg_tool_duration_ms", 0.0)),
            ),
            "last_error_type": str(
                outcome.get("error_type")
                or features.get("last_error_type")
                or ""
            ),
            "last_exit_code": int(
                outcome.get("exit_code")
                if isinstance(outcome.get("exit_code"), int)
                else features.get("last_exit_code", -1)
            ),
            "chosen_tool": _normalize_tool_label(decision),
            "success": int(outcome.get("success", 0)),
        }

        if not row["chosen_tool"]:
            continue

        validate_tool_selection_row(row)
        rows.append(row)

    return rows
