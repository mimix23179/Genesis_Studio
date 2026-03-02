"""Bonzai controller entrypoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..types.core import ActionPlan, OpenMLState
from .features import extract_features
from .rules import evaluate_rules

if TYPE_CHECKING:
    from ..abyss.store import AbyssStore


def openml_step(
    state: OpenMLState,
    *,
    store: "AbyssStore | None" = None,
    trace_id: str | None = None,
) -> ActionPlan:
    """Produce a deterministic, explainable action plan for one step."""

    features = extract_features(state)
    rule_result = evaluate_rules(state, features)
    plan = rule_result.plan

    evidence = list(plan.evidence)
    evidence.append(
        {
            "source": "bonzai.features",
            "version": features.version,
            "intent_category": features.values.get("intent_category", "other"),
        }
    )
    plan.evidence = evidence

    if store is not None and trace_id is not None:
        store.append_trace_event(
            trace_id,
            "decision",
            {
                "action_type": plan.action_type,
                "tool": plan.tool,
                "args": plan.args,
                "question": plan.question,
                "final_answer": plan.final_answer,
                "confidence": plan.confidence,
                "reasons": plan.reasons,
                "evidence": plan.evidence,
                "rule": rule_result.name,
                "feature_version": features.version,
                "features": features.values,
            },
        )

    return plan
