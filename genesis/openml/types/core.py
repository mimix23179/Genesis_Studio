"""Core OpenML contracts.

These dataclasses define stable interfaces between runtime orchestration,
controller decisions, tool execution, and trace summaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ActionType = Literal["tool", "ask_user", "final_answer"]


@dataclass(slots=True)
class OpenMLState:
    """Input state for one OpenML reasoning step."""

    user_message: str
    workspace_id: str
    session_id: str
    available_tools: list[str] = field(default_factory=list)
    recent_traces: list["TraceSummary"] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ActionPlan:
    """Controller decision envelope."""

    action_type: ActionType
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    question: str | None = None
    final_answer: str | None = None
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ToolCall:
    """Stable tool call contract."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 20_000


@dataclass(slots=True)
class ToolResult:
    """Stable tool result contract."""

    ok: bool
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(slots=True)
class TraceSummary:
    """Compact trace metadata for recent context."""

    trace_id: str
    session_id: str
    workspace_id: str
    created_at: int
    summary: str | None
    status: str
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TraceEvent:
    """Durable event in a trace timeline."""

    event_id: str
    trace_id: str
    seq: int
    ts: int
    event_type: str
    data: dict[str, Any] = field(default_factory=dict)
