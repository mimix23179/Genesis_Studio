"""Leonis evaluation gates for promotion decisions."""

from __future__ import annotations

from typing import Any


def evaluate_tool_selection_dataset(
    rows: list[dict[str, Any]],
    *,
    min_rows: int = 10,
    success_threshold: float = 0.6,
) -> dict[str, Any]:
    """Compute pass/fail metrics over exported Leonis rows."""

    row_count = len(rows)
    successes = sum(int(row.get("success", 0)) for row in rows)
    success_rate = float(successes / row_count) if row_count else 0.0

    label_counts: dict[str, int] = {}
    for row in rows:
        label = str(row.get("chosen_tool", ""))
        label_counts[label] = label_counts.get(label, 0) + 1

    passed = row_count >= min_rows and success_rate >= success_threshold
    return {
        "passed": passed,
        "row_count": row_count,
        "min_rows": min_rows,
        "successes": successes,
        "success_rate": success_rate,
        "success_threshold": success_threshold,
        "label_counts": dict(sorted(label_counts.items())),
    }


def compare_evaluations(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Compare candidate dataset metrics against baseline metrics."""

    baseline_rate = float(baseline.get("success_rate", 0.0))
    candidate_rate = float(candidate.get("success_rate", 0.0))
    baseline_rows = int(baseline.get("row_count", 0))
    candidate_rows = int(candidate.get("row_count", 0))

    delta_success_rate = candidate_rate - baseline_rate
    delta_rows = candidate_rows - baseline_rows

    recommendation = "promote" if (candidate.get("passed") and delta_success_rate >= 0.0) else "hold"

    return {
        "baseline": baseline,
        "candidate": candidate,
        "delta_success_rate": delta_success_rate,
        "delta_rows": delta_rows,
        "recommendation": recommendation,
    }
