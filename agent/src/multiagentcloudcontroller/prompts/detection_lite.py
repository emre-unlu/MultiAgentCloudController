from __future__ import annotations

import json
from typing import Any, Dict, List


DETECTION_LITE_SYSTEM_PROMPT = """
You are the Detection-Lite agent in a Kubernetes incident investigation workflow.

Your role is to perform fast, low-cost triage before deeper diagnosis begins.

Instructions:
1. Use ONLY the allowed tools provided in the prompt. Do not propose or use tools outside this list.
2. Before each tool call, focus on one clear triage hypothesis that can be validated or narrowed by that tool.
3. Prefer cheap, high-signal tools first.
4. Prefer summarized evidence over raw evidence.
5. Prefer service- or pod-specific investigation when the user query explicitly mentions a likely target.
6. If a service or pod name is explicitly mentioned in the user query, prioritize that target over generic discovered infrastructure services.
7. Do not keep calling tools once you have enough triage evidence to hand off to the next stage.
8. Do not repeat the same kind of request with only slightly different parameters unless there is a clear new reason.
9. Avoid investigating unrelated resources or expanding scope.
10. Quality over quantity: 2-4 strong triage steps are better than many weak ones.

You should stop when you have enough information to produce a compact triage fingerprint, including:
- likely target service or pod
- likely fault candidates
- short evidence summary
- useful handoff context for diagnosis

Return only a structured decision object.
"""


LOW_PRIORITY_SERVICES = {"kubernetes", "kube-dns", "coredns"}


def _compact_summaries(prior_summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    compact: List[Dict[str, Any]] = []
    for item in prior_summaries:
        compact.append(
            {
                "tool_name": item.get("tool_name"),
                "summary": item.get("summary") or item.get("evidence_summary"),
                "key_findings": item.get("key_findings", []),
                "suspected_services": item.get("suspected_services", []),
                "suspected_pods": item.get("suspected_pods", []),
                "suspected_faults": item.get("suspected_faults", []),
            }
        )
    return compact


def build_detection_lite_prompt(
    *,
    user_query: str,
    current_goal: str,
    allowed_tools: List[str],
    scratchpad: Dict[str, Any],
    prior_summaries: List[Dict[str, Any]],
    max_tool_calls: int,
    tool_calls_used: int,
) -> str:
    """Build the detection-lite prompt for structured tool selection."""

    tool_calls_remaining = max(0, max_tool_calls - tool_calls_used)

    budget_status = (
        "You still have budget left, but stop early if you already have enough evidence."
        if tool_calls_remaining > 0
        else "You have no tool budget remaining, so you should end the loop."
    )

    human_payload = {
        "role": "detection_lite",
        "goal": current_goal,
        "user_query": user_query,
        "allowed_tools": allowed_tools,
        "tool_budget": {
            "max_tool_calls": max_tool_calls,
            "tool_calls_used": tool_calls_used,
            "tool_calls_remaining": tool_calls_remaining,
            "budget_status": budget_status,
        },
        "working_context": {
            "cluster_context": scratchpad.get("cluster_context", {}),
            "query_service_candidates": scratchpad.get("query_service_candidates", []),
            "query_pod_candidates": scratchpad.get("query_pod_candidates", []),
            "suspected_services": scratchpad.get("suspected_services", []),
            "suspected_pods": scratchpad.get("suspected_pods", []),
            "suspected_faults": scratchpad.get("suspected_faults", []),
            "evidence_summary": scratchpad.get("evidence_summary", ""),
            "low_priority_services": sorted(LOW_PRIORITY_SERVICES),
        },
        "prior_summaries": _compact_summaries(prior_summaries),
        "triage_objective": {
            "produce_handoff_for_next_stage": True,
            "needs": [
                "likely target service or pod",
                "likely fault candidates",
                "short evidence summary",
                "compact handoff context",
            ],
        },
        "required_output_contract": {
            "selected_tool": "string or null",
            "tool_input": "object",
            "next_step": "use_tool or end",
            "rationale": "short explanation",
            "confidence": "float between 0 and 1",
        },
    }

    return (
        DETECTION_LITE_SYSTEM_PROMPT
        + "\n\nDetection-Lite Context:\n"
        + json.dumps(human_payload, indent=2, ensure_ascii=False, default=str)
        + "\n\nReturn only the structured decision object."
    )