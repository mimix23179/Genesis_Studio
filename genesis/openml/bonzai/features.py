"""Feature extraction for Bonzai decisioning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..types.core import OpenMLState

FEATURE_VERSION = "1"


@dataclass(slots=True)
class FeatureVector:
    """Versioned, deterministic feature vector."""

    version: str
    values: dict[str, Any]


def _intent_category(user_message: str) -> str:
    text = user_message.lower()

    debug_terms = ("error", "crash", "trace", "stack", "failed", "failure", "exception")
    search_terms = ("find", "search", "where is", "locate")
    edit_terms = ("edit", "change", "refactor", "fix", "update", "modify", "patch")
    run_terms = ("run", "test", "build", "execute")

    if any(term in text for term in debug_terms):
        return "debug"
    if any(term in text for term in search_terms):
        return "search"
    if any(term in text for term in edit_terms):
        return "edit"
    if any(term in text for term in run_terms):
        return "run"
    return "other"


def _recent_status_counts(state: OpenMLState) -> tuple[int, int]:
    failures = 0
    successes = 0
    for trace in state.recent_traces:
        normalized = trace.status.strip().lower()
        if normalized in {"ok", "success", "completed"}:
            successes += 1
        elif normalized:
            failures += 1
    return failures, successes


def _recent_tools_histogram(state: OpenMLState) -> dict[str, int]:
    tools: list[str] = []

    metadata_tools = state.metadata.get("recent_tools")
    if isinstance(metadata_tools, list):
        tools.extend(str(item) for item in metadata_tools if str(item).strip())

    if not tools:
        for trace in state.recent_traces:
            chosen = trace.metrics.get("chosen_tool")
            if isinstance(chosen, str) and chosen.strip():
                tools.append(chosen)

    histogram: dict[str, int] = {}
    for tool_name in sorted(tools):
        histogram[tool_name] = histogram.get(tool_name, 0) + 1
    return histogram


def _avg_tool_duration_ms(state: OpenMLState) -> float:
    durations: list[float] = []

    metadata_durations = state.metadata.get("recent_durations_ms")
    if isinstance(metadata_durations, list):
        for value in metadata_durations:
            try:
                durations.append(float(value))
            except (TypeError, ValueError):
                continue

    if not durations:
        for trace in state.recent_traces:
            value = trace.metrics.get("duration_ms")
            try:
                if value is not None:
                    durations.append(float(value))
            except (TypeError, ValueError):
                continue

    if not durations:
        return 0.0

    return float(sum(durations) / len(durations))


def _last_error_fields(state: OpenMLState) -> tuple[str, int]:
    last_error_type = ""
    last_exit_code = -1

    metadata_error_type = state.metadata.get("last_error_type")
    if isinstance(metadata_error_type, str):
        last_error_type = metadata_error_type

    metadata_exit_code = state.metadata.get("last_exit_code")
    if isinstance(metadata_exit_code, int):
        last_exit_code = metadata_exit_code

    for trace in state.recent_traces:
        error_type = trace.metrics.get("error_type")
        if isinstance(error_type, str) and error_type.strip():
            last_error_type = error_type
            break

    for trace in state.recent_traces:
        exit_code = trace.metrics.get("exit_code")
        if isinstance(exit_code, int):
            last_exit_code = exit_code
            break

    return last_error_type, last_exit_code


def extract_features(state: OpenMLState) -> FeatureVector:
    """Extract deterministic feature values from state and recent traces."""

    recent_failures_count, recent_successes_count = _recent_status_counts(state)
    has_git = 1 if bool(state.metadata.get("has_git", False)) else 0
    dirty_repo = 1 if bool(state.metadata.get("dirty_repo", False)) else 0

    file_count = state.metadata.get("file_count")
    if not isinstance(file_count, int):
        documents = state.metadata.get("documents")
        if isinstance(documents, list):
            file_count = len(documents)
        else:
            file_count = 0

    recent_tools_histogram = _recent_tools_histogram(state)
    avg_tool_duration_ms = _avg_tool_duration_ms(state)
    last_error_type, last_exit_code = _last_error_fields(state)

    values = {
        "intent_category": _intent_category(state.user_message),
        "recent_failures_count": recent_failures_count,
        "recent_successes_count": recent_successes_count,
        "has_git": has_git,
        "dirty_repo": dirty_repo,
        "file_count": file_count,
        "recent_tools_histogram": recent_tools_histogram,
        "avg_tool_duration_ms": avg_tool_duration_ms,
        "last_error_type": last_error_type,
        "last_exit_code": last_exit_code,
    }

    return FeatureVector(version=FEATURE_VERSION, values=values)
