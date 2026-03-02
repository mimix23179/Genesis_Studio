"""Runtime integration helpers for Bonzai decision-to-execution flow."""

from __future__ import annotations

import time
from typing import Any, Callable

from ..types.core import OpenMLState, ToolResult
from .controller import openml_step


ToolExecutor = Callable[[str, dict[str, Any]], ToolResult | dict[str, Any]]


def _normalize_tool_result(raw: ToolResult | dict[str, Any]) -> ToolResult:
    if isinstance(raw, ToolResult):
        return raw

    if isinstance(raw, dict):
        ok = bool(raw.get("ok", False))
        result = raw.get("result")
        error = raw.get("error")

        if not isinstance(result, dict):
            result = {"value": result}
        if error is not None and not isinstance(error, str):
            error = str(error)

        return ToolResult(ok=ok, result=result, error=error)

    return ToolResult(ok=False, result={}, error=f"Unsupported tool result type: {type(raw)!r}")


def execute_openml_step(
    state: OpenMLState,
    *,
    store,
    trace_id: str,
    tool_executor: ToolExecutor,
) -> dict[str, Any]:
    """Run Bonzai decisioning and tool execution with Abyss trace integration."""

    plan = openml_step(state, store=store, trace_id=trace_id)

    if plan.action_type != "tool" or not plan.tool:
        store.finish_trace(
            trace_id,
            status="ok",
            metrics={
                "action_type": plan.action_type,
                "chosen_tool": plan.tool,
                "confidence": plan.confidence,
            },
        )
        store.record_outcome(
            trace_id,
            success=True,
            data={"action_type": plan.action_type, "reasons": plan.reasons},
        )
        return {"plan": plan, "tool_result": None}

    started_ms = int(time.time() * 1000)
    store.append_trace_event(
        trace_id,
        "tool.call",
        {"tool": plan.tool, "args": plan.args, "started_ms": started_ms},
    )

    raw_result = tool_executor(plan.tool, dict(plan.args))
    result = _normalize_tool_result(raw_result)

    ended_ms = int(time.time() * 1000)
    duration_ms = max(0, ended_ms - started_ms)

    result_summary = dict(result.result)
    if len(str(result_summary)) > 500:
        result_summary = {"summary": "result truncated", "keys": sorted(result_summary.keys())}

    store.append_trace_event(
        trace_id,
        "tool.result",
        {
            "tool": plan.tool,
            "ok": result.ok,
            "result": result_summary,
            "error": result.error,
            "duration_ms": duration_ms,
            "exit_code": result.result.get("exit_code") if isinstance(result.result, dict) else None,
        },
    )

    status = "ok" if result.ok else "error"
    store.finish_trace(
        trace_id,
        status=status,
        metrics={
            "action_type": plan.action_type,
            "chosen_tool": plan.tool,
            "confidence": plan.confidence,
            "duration_ms": duration_ms,
            "error_type": "tool_error" if not result.ok else "",
            "exit_code": result.result.get("exit_code", -1),
        },
    )
    store.record_outcome(
        trace_id,
        success=result.ok,
        exit_code=result.result.get("exit_code") if isinstance(result.result, dict) else None,
        error_type="tool_error" if not result.ok else None,
        error_summary=result.error,
        data={"tool": plan.tool, "duration_ms": duration_ms},
    )

    return {"plan": plan, "tool_result": result}
