from __future__ import annotations

from typing import Any, Dict

from ...graph.state import OuterAgentState, ToolSummaryState, build_initial_tool_state
from ...retrieval.kubernetes_mcp_client import KubernetesMCPClient
from ..tool_loop import build_tool_loop


# -----------------------------------------------------------------------------
# Placeholder inner-loop node implementations for the detection-lite stage
# -----------------------------------------------------------------------------


TRIAGE_TOOL_NAME = "get_backend_status"


def detection_lite_agent_node(state: ToolSummaryState) -> ToolSummaryState:
    tool_calls_used = int(state.get("tool_calls_used", 0))
    max_tool_calls = int(state.get("max_tool_calls", 2))
    scratchpad = state.get("scratchpad", {})
    summaries = state.get("collected_summaries", [])

    if tool_calls_used >= max_tool_calls:
        state["next_step"] = "end"
        state["final_output"] = {
            "suspected_faults": scratchpad.get("suspected_faults", []),
            "suspected_services": scratchpad.get("suspected_services", []),
            "suspected_pods": scratchpad.get("suspected_pods", []),
            "evidence_summary": scratchpad.get("evidence_summary", ""),
            "supporting_summaries": summaries,
            "status": "tool_budget_exhausted",
        }
        return state

    if tool_calls_used == 0:
        state["selected_tool"] = "get_backend_status"
        state["tool_input"] = {}
        state["next_step"] = "use_tool"
        return state

    if tool_calls_used == 1:
        latest_summary = state.get("latest_summary", {})
        backend_status = latest_summary.get("backend_status", {})
        kubernetes_ok = backend_status.get("kubernetes", {}).get("status") == "OK"

        if kubernetes_ok:
            state["selected_tool"] = "get_cluster_overview"
            state["tool_input"] = {
                "namespace": scratchpad.get("cluster_context", {}).get("namespace"),
            }
            state["next_step"] = "use_tool"
        else:
            state["next_step"] = "end"
            state["final_output"] = {
                "suspected_faults": ["kubernetes_unavailable"],
                "suspected_services": [],
                "suspected_pods": [],
                "evidence_summary": "Kubernetes backend is unavailable during detection-lite.",
                "supporting_summaries": summaries,
                "status": "completed_detection_lite",
            }
        return state

    state["next_step"] = "end"
    return state



def detection_lite_tool_node(state: ToolSummaryState) -> ToolSummaryState:
    """Execute the selected Kubernetes MCP tool for lightweight triage."""

    selected_tool = state.get("selected_tool", TRIAGE_TOOL_NAME)
    tool_input = state.get("tool_input", {})

    client = KubernetesMCPClient()
    try:
        raw_result = client.call_tool(selected_tool, tool_input)
    except RuntimeError as exc:
        raw_result = {
            "error": str(exc),
            "suspected_faults": ["unknown_fault"],
            "suspected_services": [],
            "suspected_pods": [],
            "evidence_summary": "Triage tool execution failed.",
        }

    state["latest_tool_result"] = {
        "tool_name": selected_tool,
        "tool_input": tool_input,
        "raw_result": raw_result,
    }
    return state



def detection_lite_summarizer_node(state: ToolSummaryState) -> ToolSummaryState:
    latest_tool_result = state.get("latest_tool_result", {})
    raw_result = latest_tool_result.get("raw_result", {})
    tool_name = latest_tool_result.get("tool_name", TRIAGE_TOOL_NAME)

    if "error" in raw_result:
        latest_summary = {
            "tool_name": tool_name,
            "error": raw_result["error"],
            "evidence_summary": f"{tool_name} failed.",
        }
    elif tool_name == "get_backend_status":
        latest_summary = {
            "tool_name": tool_name,
            "backend_status": raw_result,
            "evidence_summary": "Backend availability collected.",
        }
    elif tool_name == "get_cluster_overview":
        latest_summary = {
            "tool_name": tool_name,
            "raw_result": raw_result,
            "suspected_faults": [],
            "suspected_services": raw_result.get("services", []),
            "suspected_pods": raw_result.get("pods", []),
            "evidence_summary": "Cluster overview collected.",
        }
    else:
        latest_summary = {
            "tool_name": tool_name,
            "raw_result": raw_result,
            "evidence_summary": f"{tool_name} completed.",
        }

    summaries = list(state.get("collected_summaries", []))
    summaries.append(latest_summary)

    state["latest_summary"] = latest_summary
    state["collected_summaries"] = summaries
    state["tool_calls_used"] = int(state.get("tool_calls_used", 0)) + 1

    if tool_name == "get_cluster_overview" or "error" in raw_result:
        state["next_step"] = "end"
        state["final_output"] = {
            "suspected_faults": latest_summary.get("suspected_faults", []),
            "suspected_services": latest_summary.get("suspected_services", []),
            "suspected_pods": latest_summary.get("suspected_pods", []),
            "evidence_summary": latest_summary.get("evidence_summary", ""),
            "supporting_summaries": summaries,
            "status": "completed_detection_lite",
        }
    else:
        state["next_step"] = "use_tool"

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
