from __future__ import annotations

from typing import Any, Dict

from ...graph.state import OuterAgentState, ToolSummaryState, build_initial_tool_state
from ...retrieval.kubernetes_mcp_client import KubernetesMCPClient
from ..tool_loop import build_tool_loop


# -----------------------------------------------------------------------------
# Placeholder inner-loop node implementations for the supervisor stage
# -----------------------------------------------------------------------------


SUPERVISOR_TOOL_NAME = "evidence_review"


def supervisor_agent_node(state: ToolSummaryState) -> ToolSummaryState:
    """Reasoning node for the supervisor stage.

    Real implementation should:
    - review the diagnosis output,
    - inspect collected evidence summaries,
    - decide whether the diagnosis is grounded and sufficient,
    - optionally request one more targeted evidence-gathering tool call,
    - produce a structured supervisor verdict.

    Current placeholder behavior:
    - if the tool budget is exhausted, finalize with uncertainty
    - otherwise, request a lightweight evidence-review tool
    - when only one tool call remains, warn the agent to summarize clearly
    """

    tool_calls_used = int(state.get("tool_calls_used", 0))
    max_tool_calls = int(state.get("max_tool_calls", 2))

    if tool_calls_used >= max_tool_calls:
        state["next_step"] = "end"
        state["final_output"] = {
            "supervisor_verdict": "finalize_with_uncertainty",
            "supervisor_feedback": "Tool budget exhausted before a confident supervisor approval.",
            "supporting_summaries": state.get("collected_summaries", []),
            "status": "tool_budget_exhausted",
        }
        return state

    tool_calls_remaining = max_tool_calls - tool_calls_used
    if tool_calls_remaining == 1:
        state["current_goal"] = (
            f"{state.get('current_goal', '')} Only one tool call remains. Use the final "
            "tool call carefully and be ready to summarize whether the diagnosis "
            "is sufficiently grounded or should be finalized with uncertainty."
        ).strip()

    state["selected_tool"] = SUPERVISOR_TOOL_NAME
    state["tool_input"] = {
        "diagnosis_result": state.get("scratchpad", {}).get("diagnosis_result", {}),
        "supervisor_feedback": state.get("scratchpad", {}).get("supervisor_feedback", ""),
    }
    state["next_step"] = "use_tool"
    return state



def supervisor_tool_node(state: ToolSummaryState) -> ToolSummaryState:
    """Execute the selected Kubernetes MCP tool for supervisor review."""

    selected_tool = state.get("selected_tool", SUPERVISOR_TOOL_NAME)
    tool_input = state.get("tool_input", {})

    client = KubernetesMCPClient()
    try:
        raw_result = client.call_tool(selected_tool, tool_input)
    except RuntimeError as exc:
        raw_result = {
            "error": str(exc),
            "grounding_ok": False,
            "notes": "Supervisor evidence review failed.",
        }

    state["latest_tool_result"] = {
        "tool_name": selected_tool,
        "tool_input": tool_input,
        "raw_result": raw_result,
    }
    return state



def supervisor_summarizer_node(state: ToolSummaryState) -> ToolSummaryState:
    """Placeholder summarizer node for the supervisor stage.

    This node runs after every tool use and compresses the evidence-review
    output into a verdict-oriented summary.
    """

    latest_tool_result = state.get("latest_tool_result", {})
    raw_result = latest_tool_result.get("raw_result", {})

    latest_summary = {
        "tool_name": latest_tool_result.get("tool_name", SUPERVISOR_TOOL_NAME),
        "grounding_ok": raw_result.get("grounding_ok", False),
        "notes": raw_result.get("notes", ""),
    }

    summaries = list(state.get("collected_summaries", []))
    summaries.append(latest_summary)

    state["latest_summary"] = latest_summary
    state["collected_summaries"] = summaries
    state["tool_calls_used"] = int(state.get("tool_calls_used", 0)) + 1

    diagnosis_result = state.get("scratchpad", {}).get("diagnosis_result", {})
    has_content = bool(diagnosis_result)
    grounding_ok = bool(latest_summary.get("grounding_ok", False))

    if has_content and grounding_ok:
        verdict = "approved"
        feedback = "Diagnosis appears sufficiently grounded based on current evidence."
    elif has_content:
        verdict = "needs_more_evidence"
        feedback = "Diagnosis exists, but the current supporting evidence is not strong enough yet."
    else:
        verdict = "finalize_with_uncertainty"
        feedback = "No usable diagnosis output was available for confident supervisor approval."

    state["next_step"] = "end"
    state["final_output"] = {
        "supervisor_verdict": verdict,
        "supervisor_feedback": feedback,
        "supporting_summaries": summaries,
        "status": "completed_supervisor_review",
    }
    return state


# -----------------------------------------------------------------------------
# Tool-loop builder for the supervisor stage
# -----------------------------------------------------------------------------


def build_supervisor_loop():
    """Build the reusable inner tool loop for supervisor review."""

    return build_tool_loop(
        agent_fn=supervisor_agent_node,
        tool_fn=supervisor_tool_node,
        summarizer_fn=supervisor_summarizer_node,
    )


# -----------------------------------------------------------------------------
# Outer workflow runner
# -----------------------------------------------------------------------------


def build_supervisor_scratchpad(state: OuterAgentState) -> Dict[str, Any]:
    """Extract supervisor-relevant context from the outer workflow state."""

    return {
        "diagnosis_result": state.get("diagnosis_result", {}),
        "retrieved_incidents": state.get("retrieved_incidents", []),
        "retrieval_confidence": state.get("retrieval_confidence", 0.0),
        "diagnosis_mode": state.get("diagnosis_mode", "full_investigation"),
        "supervisor_feedback": state.get("supervisor_feedback", ""),
        "diagnosis_attempts": state.get("diagnosis_attempts", 0),
        "max_diagnosis_attempts": state.get("max_diagnosis_attempts", 2),
    }



def build_supervisor_goal(state: OuterAgentState) -> str:
    """Create a stage-specific objective for the supervisor loop."""

    attempts = int(state.get("diagnosis_attempts", 0))
    max_attempts = int(state.get("max_diagnosis_attempts", 2))
    return (
        "Review the current diagnosis result and determine whether it is "
        "sufficiently grounded to approve. If not, decide whether another "
        f"diagnosis pass is justified. Current attempt count: {attempts}/{max_attempts}."
    )



def run_supervisor_stage(state: OuterAgentState) -> OuterAgentState:
    """Run the supervisor stage as an inner reusable tool-summary loop."""

    loop = build_supervisor_loop()
    tool_state = build_initial_tool_state(
        user_query=state.get("user_query", ""),
        current_goal=build_supervisor_goal(state),
        scratchpad=build_supervisor_scratchpad(state),
        max_tool_calls=2,
    )

    result = loop.invoke(tool_state)
    final_output = result.get("final_output", {})

    state["supervisor_verdict"] = final_output.get(
        "supervisor_verdict",
        "finalize_with_uncertainty",
    )
    state["supervisor_feedback"] = final_output.get("supervisor_feedback", "")
    return state
