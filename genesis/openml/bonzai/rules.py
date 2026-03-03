"""Deterministic rules engine for Bonzai v0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..types.core import ActionPlan, OpenMLState
from .features import FeatureVector


@dataclass(slots=True)
class RuleResult:
    """Matched rule output."""

    name: str
    plan: ActionPlan


Rule = Callable[[OpenMLState, FeatureVector], RuleResult | None]


def _make_evidence(*, rule: str, details: dict[str, object]) -> list[dict[str, object]]:
    return [{"source": "bonzai.rule", "rule": rule, **details}]


def _rule_workspace_missing(state: OpenMLState, _features: FeatureVector) -> RuleResult | None:
    if state.workspace_id.strip():
        return None

    return RuleResult(
        name="workspace-missing",
        plan=ActionPlan(
            action_type="ask_user",
            question="I need a workspace path before I can run tools. Which folder should I use?",
            confidence=0.99,
            reasons=["Workspace ID is empty, so tool routing would be unsafe."],
            evidence=_make_evidence(rule="workspace-missing", details={"workspace_id": state.workspace_id}),
        ),
    )


def _rule_repeated_failure(_state: OpenMLState, features: FeatureVector) -> RuleResult | None:
    failures = int(features.values.get("recent_failures_count", 0))
    if failures < 2:
        return None

    return RuleResult(
        name="repeated-failure",
        plan=ActionPlan(
            action_type="ask_user",
            question="Recent attempts failed repeatedly. Should I continue with safer diagnostics before editing files?",
            confidence=0.93,
            reasons=[f"Detected {failures} recent non-success traces."],
            evidence=_make_evidence(rule="repeated-failure", details={"recent_failures_count": failures}),
        ),
    )


def _rule_debug(state: OpenMLState, features: FeatureVector) -> RuleResult | None:
    if features.values.get("intent_category") != "debug":
        return None

    available = set(state.available_tools)
    reasons: list[str] = ["Detected debug intent keywords in user request."]

    if "proc.run" in available:
        return RuleResult(
            name="debug",
            plan=ActionPlan(
                action_type="tool",
                tool="proc.run",
                args={"command": "pytest -q", "timeout_ms": 120000},
                confidence=0.87,
                reasons=reasons + ["`proc.run` is available for immediate diagnostics."],
                evidence=_make_evidence(
                    rule="debug",
                    details={"intent_category": "debug", "selected_tool": "proc.run"},
                ),
            ),
        )

    if "search.ripgrep" in available:
        return RuleResult(
            name="debug",
            plan=ActionPlan(
                action_type="tool",
                tool="search.ripgrep",
                args={"query": state.user_message.strip()},
                confidence=0.74,
                reasons=reasons + ["Falling back to `search.ripgrep` because `proc.run` is unavailable."],
                evidence=_make_evidence(
                    rule="debug",
                    details={"intent_category": "debug", "selected_tool": "search.ripgrep"},
                ),
            ),
        )

    return RuleResult(
        name="debug",
        plan=ActionPlan(
            action_type="ask_user",
            question="I detected a debugging request, but no diagnostic tools are available. Should I proceed with manual inspection guidance?",
            confidence=0.45,
            reasons=reasons + ["Neither `proc.run` nor `search.ripgrep` is available."],
            evidence=_make_evidence(rule="debug", details={"intent_category": "debug", "selected_tool": "none"}),
        ),
    )


def _rule_search(state: OpenMLState, features: FeatureVector) -> RuleResult | None:
    if features.values.get("intent_category") != "search":
        return None

    available = set(state.available_tools)
    if "search.ripgrep" not in available:
        return RuleResult(
            name="search",
            plan=ActionPlan(
                action_type="ask_user",
                question="I can route this as a code search, but `search.ripgrep` is unavailable. Should I continue with a manual lookup plan?",
                confidence=0.51,
                reasons=["Detected search intent, but no search tool is available."],
                evidence=_make_evidence(rule="search", details={"intent_category": "search", "selected_tool": "none"}),
            ),
        )

    return RuleResult(
        name="search",
        plan=ActionPlan(
            action_type="tool",
            tool="search.ripgrep",
            args={"query": state.user_message.strip()},
            confidence=0.9,
            reasons=["Detected explicit search intent keywords."],
            evidence=_make_evidence(
                rule="search",
                details={"intent_category": "search", "selected_tool": "search.ripgrep"},
            ),
        ),
    )


def _rule_edit(state: OpenMLState, features: FeatureVector) -> RuleResult | None:
    if features.values.get("intent_category") != "edit":
        return None

    available = set(state.available_tools)
    reasons = ["Detected edit/refactor/fix intent; gathering safe context before patching."]

    if "git.status" in available:
        tool = "git.status"
        args = {}
        confidence = 0.83
    elif "search.ripgrep" in available:
        tool = "search.ripgrep"
        args = {"query": state.user_message.strip()}
        confidence = 0.74
    elif "fs.read" in available:
        tool = "fs.read"
        args = {"path": "."}
        confidence = 0.62
    else:
        return RuleResult(
            name="edit",
            plan=ActionPlan(
                action_type="ask_user",
                question="I can proceed with an edit plan, but tool access is limited. Should I continue with a manual patch strategy?",
                confidence=0.49,
                reasons=reasons + ["No context-gathering tools are available."],
                evidence=_make_evidence(rule="edit", details={"intent_category": "edit", "selected_tool": "none"}),
            ),
        )

    return RuleResult(
        name="edit",
        plan=ActionPlan(
            action_type="tool",
            tool=tool,
            args=args,
            confidence=confidence,
            reasons=reasons + [f"Selected `{tool}` as first context step."],
            evidence=_make_evidence(rule="edit", details={"intent_category": "edit", "selected_tool": tool}),
        ),
    )


def _fallback_rule(_state: OpenMLState, features: FeatureVector) -> RuleResult | None:
    return RuleResult(
        name="fallback",
        plan=ActionPlan(
            action_type="ask_user",
            question="Could you clarify your desired outcome in one sentence?",
            confidence=0.2,
            reasons=["No explicit rule matched strongly; prefer generation path when available."],
            evidence=_make_evidence(
                rule="fallback",
                details={"intent_category": str(features.values.get("intent_category", "other"))},
            ),
        ),
    )


ORDERED_RULES: tuple[Rule, ...] = (
    _rule_workspace_missing,
    _rule_repeated_failure,
    _rule_debug,
    _rule_search,
    _rule_edit,
    _fallback_rule,
)


def evaluate_rules(state: OpenMLState, features: FeatureVector) -> RuleResult:
    """Evaluate ordered rules. First match wins."""

    for rule in ORDERED_RULES:
        result = rule(state, features)
        if result is not None:
            return result

    raise RuntimeError("No Bonzai rule produced a result.")
