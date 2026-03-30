from __future__ import annotations

from typing import Any, Dict

from ...graph.state import OuterAgentState, ToolSummaryState, build_initial_tool_state
from ...retrieval.kubernetes_mcp_client import KubernetesMCPClient
from ..tool_loop import build_tool_loop


# -----------------------------------------------------------------------------
# Detection-lite stage
# -----------------------------------------------------------------------------


BACKEND_STATUS_TOOL = "get_backend_status"
CLUSTER_OVERVIEW_TOOL = "get_cluster_overview"


def detection_lite_agent_node(state: ToolSummaryState) -> ToolSummaryState:
    """Reasoning node for the lightweight triage stage.

    Current behavior:
    1. Call backend status first.
    2. If Kubernetes is available, call cluster overview.
    3. Stop after building a small triage fingerprint.
    """

    tool_calls_used = int(state.get("tool_calls_used", 0))
    max_tool_calls = int(state.get("max_tool_calls", 2))
    scratchpad = state.get("scratchpad", {})
    summaries = list(state.get("collected_summaries", []))

    if tool_calls_used >= max_tool_calls:
        state["next_step"] = "end"
        state["final_output"] = {
            "suspected_faults": scratchpad.get("suspected_faults", []),
            "suspected_services": scratchpad.get("suspected_services", []),
            "suspected_pods": scratchpad.get("suspected_pods", []),
            "evidence_summary": scratchpad.get("evidence_summary", ""),
            "backend_status": scratchpad.get("backend_status", {}),
            "supporting_summaries": summaries,
            "status": "tool_budget_exhausted",
        }
        return state

    if tool_calls_used == 0:
        state["selected_tool"] = BACKEND_STATUS_TOOL
        state["tool_input"] = {}
        state["next_step"] = "use_tool"
        return state

    if tool_calls_used == 1:
        latest_summary = state.get("latest_summary", {})
        backend_status = latest_summary.get("backend_status", {})
        kubernetes_ok = bool(backend_status.get("kubernetes", {}).get("available", False))

        if kubernetes_ok:
            state["selected_tool"] = CLUSTER_OVERVIEW_TOOL
            state["tool_input"] = {
                "namespace": scratchpad.get("cluster_context", {}).get("namespace"),
            }
            state["next_step"] = "use_tool"
        else:
            state["next_step"] = "end"
            state["final_output"] = {
                "suspected_faults": ["mcp_server_call_failed"],
                "suspected_services": [],
                "suspected_pods": [],
                "evidence_summary": "Kubernetes backend could not be verified during detection-lite.",
                "backend_status": backend_status,
                "supporting_summaries": summaries,
                "status": "completed_detection_lite",
            }
        return state

    state["next_step"] = "end"
    return state



def detection_lite_tool_node(state: ToolSummaryState) -> ToolSummaryState:
    """Execute the selected Kubernetes MCP tool for lightweight triage."""

    selected_tool = state.get("selected_tool", BACKEND_STATUS_TOOL)
    tool_input = state.get("tool_input", {})

    client = KubernetesMCPClient()
    try:
        raw_result = client.call_tool(selected_tool, tool_input)
    except Exception as exc:
        raw_result = {
            "ok": False,
            "message": "Triage tool execution failed.",
            "error": str(exc),
        }

    state["latest_tool_result"] = {
        "tool_name": selected_tool,
        "tool_input": tool_input,
        "raw_result": raw_result,
    }
    return state



def _extract_service_names(raw_result: Dict[str, Any]) -> list[str]:
    services = raw_result.get("services", [])
    extracted: list[str] = []
    for service in services:
        if isinstance(service, dict):
            name = service.get("name")
            if name:
                extracted.append(str(name))
    return extracted



def _extract_pod_names(raw_result: Dict[str, Any]) -> list[str]:
    pods = raw_result.get("pods", [])
    extracted: list[str] = []
    for pod in pods:
        if isinstance(pod, dict):
            name = pod.get("name")
            if name:
                extracted.append(str(name))
        elif isinstance(pod, str):
            extracted.append(pod)
    return extracted



def detection_lite_summarizer_node(state: ToolSummaryState) -> ToolSummaryState:
    """Summarize each triage tool call into a small grounded fingerprint."""

    latest_tool_result = state.get("latest_tool_result", {})
    raw_result = latest_tool_result.get("raw_result", {})
    tool_name = latest_tool_result.get("tool_name", BACKEND_STATUS_TOOL)

    if raw_result.get("error"):
        latest_summary = {
            "tool_name": tool_name,
            "error": raw_result.get("error", ""),
            "evidence_summary": f"{tool_name} failed.",
        }
    elif tool_name == BACKEND_STATUS_TOOL:
        latest_summary = {
            "tool_name": tool_name,
            "backend_status": raw_result,
            "evidence_summary": "Backend availability collected.",
        }
    elif tool_name == CLUSTER_OVERVIEW_TOOL:
        latest_summary = {
            "tool_name": tool_name,
            "backend_status": state.get("scratchpad", {}).get("backend_status", {}),
            "suspected_faults": [],
            "suspected_services": _extract_service_names(raw_result),
            "suspected_pods": _extract_pod_names(raw_result),
            "evidence_summary": "Cluster overview collected.",
            "raw_result": raw_result,
        }
    else:
        latest_summary = {
            "tool_name": tool_name,
            "raw_result": raw_result,
            "evidence_summary": f"{tool_name} completed.",
        }

    summaries = list(state.get("collected_summaries", []))
    summaries.append(latest_summary)

    scratchpad = dict(state.get("scratchpad", {}))
    if tool_name == BACKEND_STATUS_TOOL and not raw_result.get("error"):
        scratchpad["backend_status"] = raw_result

    state["scratchpad"] = scratchpad
    state["latest_summary"] = latest_summary
    state["collected_summaries"] = summaries
    state["tool_calls_used"] = int(state.get("tool_calls_used", 0)) + 1

    if tool_name == CLUSTER_OVERVIEW_TOOL or raw_result.get("error"):
        state["next_step"] = "end"
        state["final_output"] = {
            "suspected_faults": latest_summary.get("suspected_faults", []),
            "suspected_services": latest_summary.get("suspected_services", []),
            "suspected_pods": latest_summary.get("suspected_pods", []),
            "evidence_summary": latest_summary.get("evidence_summary", ""),
            "backend_status": scratchpad.get("backend_status", {}),
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
        "backend_status": {},
    }



def build_detection_lite_goal(state: OuterAgentState) -> str:
    """Create a stage-specific objective for the triage loop."""

    return (
        "Perform a lightweight Kubernetes triage pass and produce a compact "
        "incident fingerprint suitable for historical incident retrieval. First "
        "check backend availability, then collect cluster overview if Kubernetes "
        "is available. Avoid Prometheus, Jaeger, and Neo4j dependent reasoning "
        "when those backends are down."
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

