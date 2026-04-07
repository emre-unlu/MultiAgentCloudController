from __future__ import annotations

from typing import Any, Dict, List

from ...graph.state import OuterAgentState, ToolSummaryState, build_initial_tool_state
from ...retrieval.kubernetes_mcp_client import KubernetesMCPClient
from ..tool_loop import build_tool_loop
from ...llm.decision import DecisionError, decide_detection_lite_next_step
from ...tool_registry.detection_lite_tools import (
    BACKEND_STATUS_TOOL,
    CLUSTER_OVERVIEW_TOOL,
    DETECTION_LITE_TOOLS,
    POD_TRIAGE_METRICS_TOOL,
    SERVICE_TRIAGE_METRICS_TOOL,
    SUMMARIZE_POD_LOGS_TOOL,
    SUMMARIZE_SERVICE_LOGS_TOOL,
)


def _backend_available(backend_status: Dict[str, Any], name: str) -> bool:
    return bool(backend_status.get(name, {}).get("available", False))


def _extract_service_names(raw_result: Dict[str, Any]) -> List[str]:
    services = raw_result.get("services", [])
    names: List[str] = []
    for service in services:
        if isinstance(service, dict) and service.get("name"):
            names.append(str(service["name"]))
    return names


def _extract_pod_names(raw_result: Dict[str, Any]) -> List[str]:
    pods = raw_result.get("pods", [])
    names: List[str] = []
    for pod in pods:
        if isinstance(pod, dict) and pod.get("name"):
            names.append(str(pod["name"]))
        elif isinstance(pod, str):
            names.append(pod)
    return names


def _pick_relevant_service(
    user_query: str,
    service_names: List[str],
) -> str | None:
    q = user_query.lower()
    for name in service_names:
        if name.lower() in q:
            return name
    for name in service_names:
        if name != "kubernetes":
            return name
    return service_names[0] if service_names else None



def detection_lite_agent_node(state: ToolSummaryState) -> ToolSummaryState:
    tool_calls_used = int(state.get("tool_calls_used", 0))
    max_tool_calls = int(state.get("max_tool_calls", 5))
    scratchpad = dict(state.get("scratchpad", {}))
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

    allowed_tools = list(state.get("allowed_tools", [])) or list(DETECTION_LITE_TOOLS)

    try:
        decision = decide_detection_lite_next_step(
            user_query=state.get("user_query", ""),
            current_goal=state.get("current_goal", ""),
            allowed_tools=allowed_tools,
            scratchpad=scratchpad,
            prior_summaries=summaries,
            max_tool_calls=max_tool_calls,
            tool_calls_used=tool_calls_used,
        )
    except DecisionError as exc:
        state["next_step"] = "end"
        state["final_output"] = {
            "suspected_faults": scratchpad.get("suspected_faults", ["decision_failure"]),
            "suspected_services": scratchpad.get("suspected_services", []),
            "suspected_pods": scratchpad.get("suspected_pods", []),
            "evidence_summary": f"Detection-lite LLM decision failed: {exc}",
            "backend_status": scratchpad.get("backend_status", {}),
            "supporting_summaries": summaries,
            "status": "completed_detection_lite",
        }
        return state

    state["next_step"] = decision.next_step
    state["latest_rationale"] = decision.rationale
    state["latest_decision_confidence"] = decision.confidence

    if decision.next_step == "use_tool":
        if decision.selected_tool is None:
            raise DecisionError("LLM returned use_tool without a selected_tool.")
        state["selected_tool"] = decision.selected_tool
        state["tool_input"] = decision.tool_input
    else:
        state["selected_tool"] = None
        state["tool_input"] = {}
        state["final_output"] = {
            "suspected_faults": scratchpad.get("suspected_faults", []),
            "suspected_services": scratchpad.get("suspected_services", []),
            "suspected_pods": scratchpad.get("suspected_pods", []),
            "evidence_summary": scratchpad.get("evidence_summary", ""),
            "backend_status": scratchpad.get("backend_status", {}),
            "supporting_summaries": summaries,
            "status": "completed_detection_lite",
        }

    return state


def detection_lite_tool_node(state: ToolSummaryState) -> ToolSummaryState:
    selected_tool = state.get("selected_tool")
    tool_input = state.get("tool_input", {})

    if not selected_tool:
        raise RuntimeError("Detection-lite tool node entered without selected_tool.")

    client = KubernetesMCPClient()
    try:
        raw_result = client.call_tool(selected_tool, tool_input)
    except Exception as exc:
        raw_result = {
            "ok": False,
            "error": str(exc),
            "message": "Detection-lite tool execution failed.",
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
    tool_name = latest_tool_result.get("tool_name", BACKEND_STATUS_TOOL)

    summaries = list(state.get("collected_summaries", []))
    scratchpad = dict(state.get("scratchpad", {}))

    latest_summary: Dict[str, Any] = {"tool_name": tool_name}

    if raw_result.get("error"):
        latest_summary["error"] = raw_result["error"]
        latest_summary["evidence_summary"] = f"{tool_name} failed."
        summaries.append(latest_summary)
        state["scratchpad"] = scratchpad
        state["latest_summary"] = latest_summary
        state["collected_summaries"] = summaries
        state["tool_calls_used"] = int(state.get("tool_calls_used", 0)) + 1
        state["next_step"] = "end"
        state["final_output"] = {
            "suspected_faults": scratchpad.get("suspected_faults", ["tool_execution_failed"]),
            "suspected_services": scratchpad.get("suspected_services", []),
            "suspected_pods": scratchpad.get("suspected_pods", []),
            "evidence_summary": latest_summary["evidence_summary"],
            "backend_status": scratchpad.get("backend_status", {}),
            "supporting_summaries": summaries,
            "status": "completed_detection_lite",
        }
        return state

    if tool_name == BACKEND_STATUS_TOOL:
        scratchpad["backend_status"] = raw_result
        latest_summary["backend_status"] = raw_result
        latest_summary["evidence_summary"] = "Backend availability collected."

    elif tool_name == CLUSTER_OVERVIEW_TOOL:
        services = _extract_service_names(raw_result)
        pods = _extract_pod_names(raw_result)

        scratchpad["suspected_services"] = services
        scratchpad["suspected_pods"] = pods
        scratchpad["evidence_summary"] = (
            f"Cluster overview collected for namespace {raw_result.get('namespace')}. "
            f"Found {raw_result.get('service_count', 0)} services and {raw_result.get('pod_count', 0)} pods."
        )

        latest_summary["suspected_services"] = services
        latest_summary["suspected_pods"] = pods
        latest_summary["raw_result"] = raw_result
        latest_summary["evidence_summary"] = scratchpad["evidence_summary"]

    elif tool_name == SERVICE_TRIAGE_METRICS_TOOL:
        service_name = latest_tool_result.get("tool_input", {}).get("service_name")
        scratchpad["evidence_summary"] = (
            f"Collected service triage metrics for {service_name}."
        )
        latest_summary["service_name"] = service_name
        latest_summary["raw_result"] = raw_result
        latest_summary["evidence_summary"] = scratchpad["evidence_summary"]

    elif tool_name == POD_TRIAGE_METRICS_TOOL:
        pod_name = latest_tool_result.get("tool_input", {}).get("pod_name")
        scratchpad["evidence_summary"] = (
            f"Collected pod triage metrics for {pod_name}."
        )
        latest_summary["pod_name"] = pod_name
        latest_summary["raw_result"] = raw_result
        latest_summary["evidence_summary"] = scratchpad["evidence_summary"]

    elif tool_name == SUMMARIZE_SERVICE_LOGS_TOOL:
        service_name = latest_tool_result.get("tool_input", {}).get("service_name")
        scratchpad["evidence_summary"] = (
            f"Collected summarized service logs for {service_name}."
        )
        latest_summary["service_name"] = service_name
        latest_summary["raw_result"] = raw_result
        latest_summary["evidence_summary"] = scratchpad["evidence_summary"]

    elif tool_name == SUMMARIZE_POD_LOGS_TOOL:
        pod_name = latest_tool_result.get("tool_input", {}).get("pod_name")
        scratchpad["evidence_summary"] = (
            f"Collected summarized pod logs for {pod_name}."
        )
        latest_summary["pod_name"] = pod_name
        latest_summary["raw_result"] = raw_result
        latest_summary["evidence_summary"] = scratchpad["evidence_summary"]

    else:
        latest_summary["raw_result"] = raw_result
        latest_summary["evidence_summary"] = f"{tool_name} completed."

    summaries.append(latest_summary)

    state["scratchpad"] = scratchpad
    state["latest_summary"] = latest_summary
    state["collected_summaries"] = summaries
    state["tool_calls_used"] = int(state.get("tool_calls_used", 0)) + 1

    if int(state.get("tool_calls_used", 0)) >= int(state.get("max_tool_calls", 5)):
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
    else:
        state["next_step"] = "use_tool"

    return state


def build_detection_lite_loop():
    return build_tool_loop(
        agent_fn=detection_lite_agent_node,
        tool_fn=detection_lite_tool_node,
        summarizer_fn=detection_lite_summarizer_node,
    )

def _extract_query_service_candidates(user_query: str) -> list[str]:
    q = user_query.lower()
    candidates: list[str] = []

    for name in ["frontend", "backend", "auth", "gateway", "api", "web"]:
        if name in q:
            candidates.append(name)

    return candidates


def _extract_query_pod_candidates(user_query: str) -> list[str]:
    q = user_query.lower()
    candidates: list[str] = []

    # simple placeholder: later you can do better parsing
    for token in q.replace(",", " ").split():
        if "pod" in token:
            candidates.append(token)

    return candidates


def build_detection_lite_scratchpad(state: OuterAgentState) -> Dict[str, Any]:
    user_query = state.get("user_query", "")

    return {
        "cluster_context": state.get("cluster_context", {}),
        "query_service_candidates": _extract_query_service_candidates(user_query),
        "query_pod_candidates": _extract_query_pod_candidates(user_query),
        "suspected_faults": state.get("suspected_faults", []),
        "suspected_services": state.get("suspected_services", []),
        "suspected_pods": state.get("suspected_pods", []),
        "evidence_summary": state.get("evidence_summary", ""),
        "backend_status": {},
    }


def build_detection_lite_goal(state: OuterAgentState) -> str:
    return (
        "Perform a lightweight triage pass. Use backend status first, then "
        "cluster overview, then cheap metrics and log summaries when useful. "
        "Produce a compact fingerprint with likely affected services or pods."
    )


def run_detection_lite_stage(state: OuterAgentState) -> OuterAgentState:
    loop = build_detection_lite_loop()
    tool_state = build_initial_tool_state(
        user_query=state.get("user_query", ""),
        current_goal=build_detection_lite_goal(state),
        scratchpad=build_detection_lite_scratchpad(state),
        max_tool_calls=5,
    )
    tool_state["allowed_tools"] = list(DETECTION_LITE_TOOLS)

    result = loop.invoke(tool_state)
    final_output = result.get("final_output", {})

    state["detection_lite_result"] = final_output
    state["suspected_faults"] = final_output.get("suspected_faults", [])
    state["suspected_services"] = final_output.get("suspected_services", [])
    state["suspected_pods"] = final_output.get("suspected_pods", [])
    state["evidence_summary"] = final_output.get("evidence_summary", "")
    return state




