from __future__ import annotations

from typing import Any, Dict

from ...graph.state import OuterAgentState, ToolSummaryState, build_initial_tool_state
from ..tool_loop import build_tool_loop


# -----------------------------------------------------------------------------
# Placeholder inner-loop node implementations for the detection-lite stage
# -----------------------------------------------------------------------------


TRIAGE_TOOL_NAME = "cluster_triage_overview"


def detection_lite_agent_node(state: ToolSummaryState) -> ToolSummaryState:
    """Reasoning node for the lightweight triage stage.

    Real implementation should:
    - inspect the current triage goal,
    - reason over scratchpad + collected summaries,
    - select a small number of cheap/high-value tools,
    - stop once it has enough evidence to prepare incident retrieval,
    - write a compact triage result into `final_output`.

    Current placeholder behavior:
    - if the tool budget is exhausted, stop and emit a minimal triage result
    - otherwise, request a single cheap cluster triage tool
    """

    tool_calls_used = int(state.get("tool_calls_used", 0))
    max_tool_calls = int(state.get("max_tool_calls", 2))
    scratchpad = state.get("scratchpad", {})

    if tool_calls_used >= max_tool_calls:
        state["next_step"] = "end"
        state["final_output"] = {
            "suspected_faults": scratchpad.get("suspected_faults", []),
            "suspected_services": scratchpad.get("suspected_services", []),
            "suspected_pods": scratchpad.get("suspected_pods", []),
            "evidence_summary": scratchpad.get("evidence_summary", ""),
            "supporting_summaries": state.get("collected_summaries", []),
            "status": "tool_budget_exhausted",
        }
        return state

    state["selected_tool"] = TRIAGE_TOOL_NAME
    state["tool_input"] = {
        "cluster_context": scratchpad.get("cluster_context", {}),
        "user_query": state.get("user_query", ""),
    }
    state["next_step"] = "use_tool"
    return state



def detection_lite_tool_node(state: ToolSummaryState) -> ToolSummaryState:
    """Placeholder tool execution node for lightweight triage.

    Real implementation should call a cheap MCP tool or a small bundle of
    observability tools from Kubernetes-Mcp and store the raw output in
    `latest_tool_result`.
    """

    selected_tool = state.get("selected_tool", TRIAGE_TOOL_NAME)
    tool_input = state.get("tool_input", {})

    state["latest_tool_result"] = {
        "tool_name": selected_tool,
        "tool_input": tool_input,
        "raw_result": {
            "suspected_faults": ["unknown_fault"],
            "suspected_services": [],
            "suspected_pods": [],
            "evidence_summary": "Placeholder triage output from a cheap cluster overview tool.",
        },
    }
    return state



def detection_lite_summarizer_node(state: ToolSummaryState) -> ToolSummaryState:
    """Placeholder summarizer node for lightweight triage.

    Real implementation should compress the raw triage output into a compact,
    retrieval-friendly fingerprint with candidate services, pods, fault types,
    and a short evidence summary.

    This node runs after every tool use.
    """

    latest_tool_result = state.get("latest_tool_result", {})
    raw_result = latest_tool_result.get("raw_result", {})

    latest_summary = {
        "tool_name": latest_tool_result.get("tool_name", TRIAGE_TOOL_NAME),
        "suspected_faults": raw_result.get("suspected_faults", []),
        "suspected_services": raw_result.get("suspected_services", []),
        "suspected_pods": raw_result.get("suspected_pods", []),
        "evidence_summary": raw_result.get("evidence_summary", ""),
    }

    summaries = list(state.get("collected_summaries", []))
    summaries.append(latest_summary)

    state["latest_summary"] = latest_summary
    state["collected_summaries"] = summaries
    state["tool_calls_used"] = int(state.get("tool_calls_used", 0)) + 1

    # Placeholder stopping rule: one summarized triage pass is enough.
    state["next_step"] = "end"
    state["final_output"] = {
        "suspected_faults": latest_summary.get("suspected_faults", []),
        "suspected_services": latest_summary.get("suspected_services", []),
        "suspected_pods": latest_summary.get("suspected_pods", []),
        "evidence_summary": latest_summary.get("evidence_summary", ""),
        "supporting_summaries": summaries,
        "status": "completed_placeholder_detection_lite",
    }
    return state


# -----------------------------------------------------------------------------
# Tool-loop builder for the detection-lite stage
# -----------------------------------------------------------------------------


def build_detection_lite_loop():
    """Build the reusable inner tool loop for lightweight triage."""

    return build_tool_loop(
        agent_fn=detection_lite_agent_node,
        tool_fn=detection_lite_tool_node,
        summarizer_fn=detection_lite_summarizer_node,
    )


# -----------------------------------------------------------------------------
# Outer workflow runner
# -----------------------------------------------------------------------------


def build_detection_lite_scratchpad(state: OuterAgentState) -> Dict[str, Any]:
    """Extract triage-relevant context from the outer workflow state."""

    return {
        "cluster_context": state.get("cluster_context", {}),
        "suspected_faults": state.get("suspected_faults", []),
        "suspected_services": state.get("suspected_services", []),
        "suspected_pods": state.get("suspected_pods", []),
        "evidence_summary": state.get("evidence_summary", ""),
    }



def build_detection_lite_goal(state: OuterAgentState) -> str:
    """Create a stage-specific objective for the triage loop."""

    return (
        "Perform a lightweight Kubernetes triage pass and produce a compact "
        "incident fingerprint suitable for historical incident retrieval. Focus "
        "on likely fault types, affected services or pods, and a short grounded "
        "evidence summary without attempting full diagnosis."
    )



def run_detection_lite_stage(state: OuterAgentState) -> OuterAgentState:
    """Run the detection-lite stage as an inner reusable tool-summary loop."""

    loop = build_detection_lite_loop()
    tool_state = build_initial_tool_state(
        user_query=state.get("user_query", ""),
        current_goal=build_detection_lite_goal(state),
        scratchpad=build_detection_lite_scratchpad(state),
        max_tool_calls=2,
    )

    result = loop.invoke(tool_state)
    final_output = result.get("final_output", {})

    state["detection_lite_result"] = final_output
    state["suspected_faults"] = final_output.get("suspected_faults", [])
    state["suspected_services"] = final_output.get("suspected_services", [])
    state["suspected_pods"] = final_output.get("suspected_pods", [])
    state["evidence_summary"] = final_output.get("evidence_summary", "")
    return state
