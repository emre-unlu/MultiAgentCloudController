from __future__ import annotations

from typing import Any, Dict

from ...graph.state import OuterAgentState, ToolSummaryState, build_initial_tool_state
from ...retrieval.kubernetes_mcp_client import KubernetesMCPClient
from ..tool_loop import build_tool_loop


# -----------------------------------------------------------------------------
# Placeholder inner-loop node implementations for the diagnosis stage
# -----------------------------------------------------------------------------


def diagnosis_agent_node(state: ToolSummaryState) -> ToolSummaryState:
    """Reasoning node for the diagnosis stage.

    Real implementation should:
    - inspect the current diagnosis goal,
    - reason over the scratchpad and collected summaries,
    - select the next MCP tool to call,
    - terminate when enough evidence has been gathered,
    - write a structured diagnosis object into `final_output`.

    Current placeholder behavior:
    - if the tool budget is exhausted, stop and emit a minimal diagnosis result
    - otherwise, request a tool call
    - when only one tool call remains, explicitly warn the agent to make the
      final tool use count and prepare to summarize its findings
    """

    tool_calls_used = int(state.get("tool_calls_used", 0))
    max_tool_calls = int(state.get("max_tool_calls", 5))

    if tool_calls_used >= max_tool_calls:
        state["next_step"] = "end"
        state["final_output"] = {
            "mode": state.get("scratchpad", {}).get("diagnosis_mode", "full_investigation"),
            "detection": {},
            "localization": {},
            "analysis": {},
            "supporting_summaries": state.get("collected_summaries", []),
            "status": "tool_budget_exhausted",
        }
        return state

    tool_calls_remaining = max_tool_calls - tool_calls_used
    if tool_calls_remaining == 1:
        state["current_goal"] = (
            f"{state.get('current_goal', '')} Only one tool call remains. Use the final "
            "tool call carefully and be ready to summarize the overall findings "
            "clearly after this step."
        ).strip()

    state["selected_tool"] = state.get("selected_tool", "") or "cluster_overview"
    state["tool_input"] = state.get("tool_input", {}) or {
        "focus_services": state.get("scratchpad", {}).get("suspected_services", []),
        "focus_pods": state.get("scratchpad", {}).get("suspected_pods", []),
    }
    state["next_step"] = "use_tool"
    return state



def diagnosis_tool_node(state: ToolSummaryState) -> ToolSummaryState:
    """Execute the selected Kubernetes MCP tool for diagnosis."""

    selected_tool = state.get("selected_tool", "cluster_overview")
    tool_input = state.get("tool_input", {})

    client = KubernetesMCPClient()
    try:
        raw_result = client.call_tool(selected_tool, tool_input)
    except RuntimeError as exc:
        raw_result = {
            "error": str(exc),
            "message": "Diagnosis tool execution failed.",
        }

    state["latest_tool_result"] = {
        "tool_name": selected_tool,
        "tool_input": tool_input,
        "raw_result": raw_result,
    }
    return state



def diagnosis_summarizer_node(state: ToolSummaryState) -> ToolSummaryState:
    """Placeholder summarizer node for diagnosis.

    Real implementation should compress raw tool output into a compact and
    structured summary suitable for the next reasoning step.
    """

    latest_tool_result = state.get("latest_tool_result", {})
    latest_summary = {
        "tool_name": latest_tool_result.get("tool_name", ""),
        "summary": latest_tool_result.get("raw_result", {}).get("message")
        or latest_tool_result.get("raw_result", {}).get("raw")
        or "Diagnosis tool executed.",
    }

    summaries = list(state.get("collected_summaries", []))
    summaries.append(latest_summary)

    state["latest_summary"] = latest_summary
    state["collected_summaries"] = summaries
    state["tool_calls_used"] = int(state.get("tool_calls_used", 0)) + 1

    # Placeholder stopping rule: stop after one summarized tool call.
    state["next_step"] = "end"
    state["final_output"] = {
        "mode": state.get("scratchpad", {}).get("diagnosis_mode", "full_investigation"),
        "detection": {
            "suspected_faults": state.get("scratchpad", {}).get("suspected_faults", []),
        },
        "localization": {
            "suspected_services": state.get("scratchpad", {}).get("suspected_services", []),
            "suspected_pods": state.get("scratchpad", {}).get("suspected_pods", []),
        },
        "analysis": {
            "best_incident_match": state.get("scratchpad", {}).get("best_incident_match"),
            "retrieval_confidence": state.get("scratchpad", {}).get("retrieval_confidence", 0.0),
        },
        "supporting_summaries": summaries,
        "status": "completed_diagnosis",
    }
    return state


# -----------------------------------------------------------------------------
# Tool-loop builder for the diagnosis stage
# -----------------------------------------------------------------------------


def build_diagnosis_loop():
    """Build the reusable inner tool loop for diagnosis."""

    return build_tool_loop(
        agent_fn=diagnosis_agent_node,
        tool_fn=diagnosis_tool_node,
        summarizer_fn=diagnosis_summarizer_node,
    )


# -----------------------------------------------------------------------------
# Outer workflow runner
# -----------------------------------------------------------------------------


def build_diagnosis_scratchpad(state: OuterAgentState) -> Dict[str, Any]:
    """Extract diagnosis-relevant context from the outer workflow state."""

    return {
        "cluster_context": state.get("cluster_context", {}),
        "diagnosis_mode": state.get("diagnosis_mode", "full_investigation"),
        "suspected_faults": state.get("suspected_faults", []),
        "suspected_services": state.get("suspected_services", []),
        "suspected_pods": state.get("suspected_pods", []),
        "evidence_summary": state.get("evidence_summary", ""),
        "retrieved_incidents": state.get("retrieved_incidents", []),
        "best_incident_match": state.get("best_incident_match"),
        "retrieval_confidence": state.get("retrieval_confidence", 0.0),
        "preload_context": state.get("preload_context", {}),
        "mitigation_hints": state.get("mitigation_hints", []),
        "previous_supervisor_feedback": state.get("supervisor_feedback", ""),
    }



def build_diagnosis_goal(state: OuterAgentState) -> str:
    """Create a stage-specific objective for the diagnosis loop."""

    mode = state.get("diagnosis_mode", "full_investigation")
    if mode == "incident_guided":
        return (
            "Investigate the current Kubernetes incident using both live cluster "
            "evidence and the retrieved historical incident context. Validate or "
            "reject the historical match before producing a structured diagnosis."
        )

    return (
        "Investigate the current Kubernetes incident from scratch using live "
        "cluster evidence and produce a structured diagnosis covering detection, "
        "localization, and analysis."
    )



def run_diagnosis_stage(state: OuterAgentState) -> OuterAgentState:
    """Run the diagnosis stage as an inner reusable tool-summary loop.

    This function is intended to be used by the outer workflow's diagnosis node.
    """

    loop = build_diagnosis_loop()
    tool_state = build_initial_tool_state(
        user_query=state.get("user_query", ""),
        current_goal=build_diagnosis_goal(state),
        scratchpad=build_diagnosis_scratchpad(state),
        max_tool_calls=5,
    )

    result = loop.invoke(tool_state)
    state["diagnosis_result"] = result.get("final_output", {})
    return state
