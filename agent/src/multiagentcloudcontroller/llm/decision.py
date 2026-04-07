from __future__ import annotations

from typing import Any, Dict, List

from .client import LLMClientError, get_llm_client
from .schemas import AgentContext, SupervisorDecision, ToolDecision, ToolSummary
from ..prompts.detection_lite import build_detection_lite_prompt


class DecisionError(RuntimeError):
    """Raised when an LLM decision cannot be produced or validated."""


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------



def _normalize_prior_summaries(prior_summaries: List[Any]) -> List[ToolSummary]:
    normalized: List[ToolSummary] = []
    for item in prior_summaries:
        if isinstance(item, ToolSummary):
            normalized.append(item)
        elif isinstance(item, dict):
            if "summary" not in item and "evidence_summary" in item:
                item = {
                    "tool_name": item.get("tool_name", "unknown_tool"),
                    "summary": item.get("summary") or item.get("evidence_summary", ""),
                    "key_findings": item.get("key_findings", []),
                    "suspected_services": item.get("suspected_services", []),
                    "suspected_pods": item.get("suspected_pods", []),
                    "suspected_faults": item.get("suspected_faults", []),
                    "raw_result_excerpt": item.get("raw_result_excerpt"),
                }
            normalized.append(ToolSummary.model_validate(item))
        else:
            normalized.append(
                ToolSummary(
                    tool_name="unknown_tool",
                    summary=str(item),
                )
            )
    return normalized



def _normalize_agent_context(**kwargs: Any) -> AgentContext:
    prior_summaries = _normalize_prior_summaries(kwargs.pop("prior_summaries", []))
    return AgentContext(prior_summaries=prior_summaries, **kwargs)



def _validate_tool_decision(decision: ToolDecision, allowed_tools: List[str]) -> ToolDecision:
    if decision.next_step == "end":
        decision.selected_tool = None
        decision.tool_input = {}
        return decision

    if not decision.selected_tool:
        raise DecisionError("LLM returned next_step='use_tool' without a selected_tool.")

    if decision.selected_tool not in allowed_tools:
        raise DecisionError(
            f"LLM selected forbidden tool '{decision.selected_tool}'. Allowed tools: {allowed_tools}"
        )

    if decision.tool_input is None:
        decision.tool_input = {}

    return decision


# -----------------------------------------------------------------------------
# Public decision functions
# -----------------------------------------------------------------------------



def decide_detection_lite_next_step(
    *,
    user_query: str,
    current_goal: str,
    allowed_tools: List[str],
    scratchpad: Dict[str, Any],
    prior_summaries: List[Any],
    max_tool_calls: int,
    tool_calls_used: int,
) -> ToolDecision:
    """Get the next structured decision for the detection-lite agent."""

    context = _normalize_agent_context(
        role="detection_lite",
        user_query=user_query,
        current_goal=current_goal,
        allowed_tools=allowed_tools,
        backend_status={},
        scratchpad=scratchpad,
        prior_summaries=prior_summaries,
        max_tool_calls=max_tool_calls,
        tool_calls_used=tool_calls_used,
    )

    prompt = build_detection_lite_prompt(
        user_query=context.user_query,
        current_goal=context.current_goal,
        allowed_tools=context.allowed_tools,
        scratchpad=context.scratchpad,
        prior_summaries=[summary.model_dump() for summary in context.prior_summaries],
        max_tool_calls=context.max_tool_calls,
        tool_calls_used=context.tool_calls_used,
    )

    try:
        client = get_llm_client()
        decision = client.invoke_structured(prompt, ToolDecision)
    except LLMClientError as exc:
        raise DecisionError(f"Detection-lite LLM decision failed: {exc}") from exc

    return _validate_tool_decision(decision, allowed_tools)



def decide_supervisor_verdict(
    *,
    user_query: str,
    current_goal: str,
    allowed_tools: List[str],
    scratchpad: Dict[str, Any],
    prior_summaries: List[Any],
    max_tool_calls: int,
    tool_calls_used: int,
    prompt_builder,
) -> SupervisorDecision:
    """Generic structured supervisor verdict helper.

    `prompt_builder` should be a callable that returns the supervisor prompt text.
    Keeping it injected lets you add the supervisor prompt file later without
    having to rewrite this function.
    """

    context = _normalize_agent_context(
        role="supervisor",
        user_query=user_query,
        current_goal=current_goal,
        allowed_tools=allowed_tools,
        backend_status={},
        scratchpad=scratchpad,
        prior_summaries=prior_summaries,
        max_tool_calls=max_tool_calls,
        tool_calls_used=tool_calls_used,
    )

    prompt = prompt_builder(
        user_query=context.user_query,
        current_goal=context.current_goal,
        allowed_tools=context.allowed_tools,
        scratchpad=context.scratchpad,
        prior_summaries=[summary.model_dump() for summary in context.prior_summaries],
        max_tool_calls=context.max_tool_calls,
        tool_calls_used=context.tool_calls_used,
    )

    try:
        client = get_llm_client()
        verdict = client.invoke_structured(prompt, SupervisorDecision)
    except LLMClientError as exc:
        raise DecisionError(f"Supervisor LLM verdict failed: {exc}") from exc

    return verdict
