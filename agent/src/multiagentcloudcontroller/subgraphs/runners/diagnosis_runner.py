from __future__ import annotations

from typing import Any, Dict, List

from ...graph.state import OuterAgentState, ToolSummaryState, build_initial_tool_state
from ...retrieval.kubernetes_mcp_client import KubernetesMCPClient
from ...tool_registry.diagnosis_tools import (
    EXEC_KUBECTL_TOOL,
    EXEC_SHELL_TOOL,
    GET_PODS_FROM_SERVICE_TOOL,
    GET_POD_METRICS_TOOL,
    GET_POD_TRIAGE_METRICS_TOOL,
    GET_SERVICE_DEPENDENCIES_TOOL,
    GET_SERVICE_MAP_TOOL,
    GET_SERVICES_FROM_POD_TOOL,
    GET_SERVICES_USED_BY_TOOL,
    GET_SERVICE_METRICS_TOOL,
    GET_SERVICE_TRIAGE_METRICS_TOOL,
    GET_TRACE_DETAILS_TOOL,
    GET_TRACE_SUMMARIES_TOOL,
    SUMMARIZE_POD_LOGS_TOOL,
    SUMMARIZE_SERVICE_LOGS_TOOL,
)
from ..tool_loop import build_tool_loop


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _backend_available(backend_status: Dict[str, Any], name: str) -> bool:
    return bool(backend_status.get(name, {}).get("available", False))



def _pick_relevant_service(user_query: str, service_names: List[str]) -> str | None:
    q = user_query.lower()
    for name in service_names:
        if name.lower() in q:
            return name
    for name in service_names:
        if name != "kubernetes":
            return name
    return service_names[0] if service_names else None



def _pick_relevant_pod(user_query: str, pod_names: List[str]) -> str | None:
    q = user_query.lower()
    for name in pod_names:
        if name.lower() in q:
            return name
    return pod_names[0] if pod_names else None



def _extract_pod_names(raw_result: Dict[str, Any]) -> List[str]:
    pods = raw_result.get("pods", [])
    names: List[str] = []
    for pod in pods:
        if isinstance(pod, dict) and pod.get("name"):
            names.append(str(pod["name"]))
        elif isinstance(pod, str):
            names.append(pod)
    return names



def _extract_service_names(raw_result: Dict[str, Any]) -> List[str]:
    services = raw_result.get("services", [])
    names: List[str] = []
    for service in services:
        if isinstance(service, dict) and service.get("name"):
            names.append(str(service["name"]))
        elif isinstance(service, str):
            names.append(service)
    return names



def _append_unique(items: List[str], new_items: List[str]) -> List[str]:
    out = list(items)
    for item in new_items:
        if item not in out:
            out.append(item)
    return out


# -----------------------------------------------------------------------------
# Inner-loop node implementations for diagnosis
# -----------------------------------------------------------------------------


MAX_LOGIC_STEPS = 8



def diagnosis_agent_node(state: ToolSummaryState) -> ToolSummaryState:
    """Rule-based diagnosis node.

    Current behavior:
    - Start from detection-lite output.
    - Prefer service-centric investigation first.
    - Use metrics if Prometheus is available.
    - Use traces if Jaeger is available.
    - Use dependency tools if Neo4j is available.
    - Use exec_kubectl / exec_shell only as fallback.
    """

    tool_calls_used = int(state.get("tool_calls_used", 0))
    max_tool_calls = int(state.get("max_tool_calls", MAX_LOGIC_STEPS))
    scratchpad = dict(state.get("scratchpad", {}))
    summaries = list(state.get("collected_summaries", []))

    if tool_calls_used >= max_tool_calls:
        state["next_step"] = "end"
        state["final_output"] = {
            "mode": "full_investigation",
            "detection": scratchpad.get("detection", {}),
            "localization": scratchpad.get("localization", {}),
            "analysis": scratchpad.get("analysis", {}),
            "suspected_services": scratchpad.get("suspected_services", []),
            "suspected_pods": scratchpad.get("suspected_pods", []),
            "supporting_summaries": summaries,
            "status": "tool_budget_exhausted",
        }
        return state

    backend_status = scratchpad.get("backend_status", {})
    suspected_services = list(scratchpad.get("suspected_services", []))
    suspected_pods = list(scratchpad.get("suspected_pods", []))
    user_query = state.get("user_query", "")
    namespace = scratchpad.get("cluster_context", {}).get("namespace")

    target_service = _pick_relevant_service(user_query, suspected_services)
    target_pod = _pick_relevant_pod(user_query, suspected_pods)

    latest_tool_name = state.get("latest_tool_result", {}).get("tool_name")
    completed_tools = [s.get("tool_name") for s in summaries if s.get("tool_name")]

    def not_yet(tool_name: str) -> bool:
        return tool_name not in completed_tools

    # Step 1: If we have a service, map to pods first.
    if target_service and not_yet(GET_PODS_FROM_SERVICE_TOOL):
        state["selected_tool"] = GET_PODS_FROM_SERVICE_TOOL
        state["tool_input"] = {"service_name": target_service, "namespace": namespace}
        state["next_step"] = "use_tool"
        return state

    # Step 2: cheap service metrics if Prometheus is available.
    if target_service and _backend_available(backend_status, "prometheus") and not_yet(GET_SERVICE_TRIAGE_METRICS_TOOL):
        state["selected_tool"] = GET_SERVICE_TRIAGE_METRICS_TOOL
        state["tool_input"] = {"service_name": target_service, "namespace": namespace}
        state["next_step"] = "use_tool"
        return state

    # Step 3: summarized service logs.
    if target_service and not_yet(SUMMARIZE_SERVICE_LOGS_TOOL):
        state["selected_tool"] = SUMMARIZE_SERVICE_LOGS_TOOL
        state["tool_input"] = {"service_name": target_service, "namespace": namespace}
        state["next_step"] = "use_tool"
        return state

    # Step 4: pod-focused metrics if we now know a pod and Prometheus is available.
    if target_pod and _backend_available(backend_status, "prometheus") and not_yet(GET_POD_TRIAGE_METRICS_TOOL):
        state["selected_tool"] = GET_POD_TRIAGE_METRICS_TOOL
        state["tool_input"] = {"pod_name": target_pod, "namespace": namespace}
        state["next_step"] = "use_tool"
        return state

    # Step 5: summarized pod logs.
    if target_pod and not_yet(SUMMARIZE_POD_LOGS_TOOL):
        state["selected_tool"] = SUMMARIZE_POD_LOGS_TOOL
        state["tool_input"] = {"pod_name": target_pod, "namespace": namespace}
        state["next_step"] = "use_tool"
        return state

    # Step 6: deeper service metrics.
    if target_service and _backend_available(backend_status, "prometheus") and not_yet(GET_SERVICE_METRICS_TOOL):
        state["selected_tool"] = GET_SERVICE_METRICS_TOOL
        state["tool_input"] = {"service_name": target_service, "namespace": namespace}
        state["next_step"] = "use_tool"
        return state

    # Step 7: deeper pod metrics.
    if target_pod and _backend_available(backend_status, "prometheus") and not_yet(GET_POD_METRICS_TOOL):
        state["selected_tool"] = GET_POD_METRICS_TOOL
        state["tool_input"] = {"pod_name": target_pod, "namespace": namespace}
        state["next_step"] = "use_tool"
        return state

    # Step 8: traces if Jaeger is available.
    if target_service and _backend_available(backend_status, "jaeger") and not_yet(GET_TRACE_SUMMARIES_TOOL):
        state["selected_tool"] = GET_TRACE_SUMMARIES_TOOL
        state["tool_input"] = {"service_name": target_service, "lookback": "15m", "limit": 10, "only_errors": True}
        state["next_step"] = "use_tool"
        return state

    # Step 9: dependency tools if Neo4j is available.
    if target_service and _backend_available(backend_status, "neo4j") and not_yet(GET_SERVICE_DEPENDENCIES_TOOL):
        state["selected_tool"] = GET_SERVICE_DEPENDENCIES_TOOL
        state["tool_input"] = {"service_name": target_service}
        state["next_step"] = "use_tool"
        return state

    if target_service and _backend_available(backend_status, "neo4j") and not_yet(GET_SERVICES_USED_BY_TOOL):
        state["selected_tool"] = GET_SERVICES_USED_BY_TOOL
        state["tool_input"] = {"service_name": target_service}
        state["next_step"] = "use_tool"
        return state

    if target_service and _backend_available(backend_status, "neo4j") and not_yet(GET_SERVICE_MAP_TOOL):
        state["selected_tool"] = GET_SERVICE_MAP_TOOL
        state["tool_input"] = {"service_name": target_service, "depth": 2}
        state["next_step"] = "use_tool"
        return state

    # Last resort: kubectl or shell for direct inspection.
    if target_service and not_yet(EXEC_KUBECTL_TOOL):
        state["selected_tool"] = EXEC_KUBECTL_TOOL
        state["tool_input"] = {"command": f"get pods -n {namespace} -o wide" if namespace else "get pods -A -o wide"}
        state["next_step"] = "use_tool"
        return state

    if not_yet(EXEC_SHELL_TOOL):
        shell_cmd = "kubectl get ns"
        if namespace:
            shell_cmd = f"kubectl get pods -n {namespace}"
        state["selected_tool"] = EXEC_SHELL_TOOL
        state["tool_input"] = {"command": shell_cmd}
        state["next_step"] = "use_tool"
        return state

    state["next_step"] = "end"
    state["final_output"] = {
        "mode": "full_investigation",
        "detection": scratchpad.get("detection", {}),
        "localization": scratchpad.get("localization", {}),
        "analysis": scratchpad.get("analysis", {}),
        "suspected_services": suspected_services,
        "suspected_pods": suspected_pods,
        "supporting_summaries": summaries,
        "status": "completed_diagnosis_pass",
    }
    return state



def diagnosis_tool_node(state: ToolSummaryState) -> ToolSummaryState:
    selected_tool = state.get("selected_tool", GET_PODS_FROM_SERVICE_TOOL)
    tool_input = state.get("tool_input", {})

    client = KubernetesMCPClient()
    try:
        raw_result = client.call_tool(selected_tool, tool_input)
    except Exception as exc:
        raw_result = {
            "ok": False,
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
    latest_tool_result = state.get("latest_tool_result", {})
    raw_result = latest_tool_result.get("raw_result", {})
    tool_name = latest_tool_result.get("tool_name", GET_PODS_FROM_SERVICE_TOOL)
    tool_input = latest_tool_result.get("tool_input", {})

    summaries = list(state.get("collected_summaries", []))
    scratchpad = dict(state.get("scratchpad", {}))
    latest_summary: Dict[str, Any] = {"tool_name": tool_name}

    if raw_result.get("error"):
        latest_summary["error"] = raw_result["error"]
        latest_summary["summary"] = f"{tool_name} failed."
        summaries.append(latest_summary)
        state["scratchpad"] = scratchpad
        state["latest_summary"] = latest_summary
        state["collected_summaries"] = summaries
        state["tool_calls_used"] = int(state.get("tool_calls_used", 0)) + 1
        state["next_step"] = "use_tool"
        return state

    if tool_name == GET_PODS_FROM_SERVICE_TOOL:
        pod_names = _extract_pod_names(raw_result)
        scratchpad["suspected_pods"] = _append_unique(scratchpad.get("suspected_pods", []), pod_names)
        latest_summary["pod_names"] = pod_names
        latest_summary["summary"] = f"Mapped service {tool_input.get('service_name')} to pods."
        scratchpad.setdefault("localization", {})["pods_from_service"] = raw_result

    elif tool_name == GET_SERVICES_FROM_POD_TOOL:
        service_names = _extract_service_names(raw_result)
        scratchpad["suspected_services"] = _append_unique(scratchpad.get("suspected_services", []), service_names)
        latest_summary["service_names"] = service_names
        latest_summary["summary"] = f"Mapped pod {tool_input.get('pod_name')} to services."
        scratchpad.setdefault("localization", {})["services_from_pod"] = raw_result

    elif tool_name in {SUMMARIZE_SERVICE_LOGS_TOOL, SUMMARIZE_POD_LOGS_TOOL}:
        latest_summary["raw_result"] = raw_result
        latest_summary["summary"] = f"Collected log summary from {tool_name}."
        scratchpad.setdefault("analysis", {})[tool_name] = raw_result

    elif tool_name in {GET_SERVICE_TRIAGE_METRICS_TOOL, GET_POD_TRIAGE_METRICS_TOOL, GET_SERVICE_METRICS_TOOL, GET_POD_METRICS_TOOL}:
        latest_summary["raw_result"] = raw_result
        latest_summary["summary"] = f"Collected metrics from {tool_name}."
        scratchpad.setdefault("detection", {})[tool_name] = raw_result

    elif tool_name in {GET_TRACE_SUMMARIES_TOOL, GET_TRACE_DETAILS_TOOL}:
        latest_summary["raw_result"] = raw_result
        latest_summary["summary"] = f"Collected tracing evidence from {tool_name}."
        scratchpad.setdefault("analysis", {})[tool_name] = raw_result

    elif tool_name in {GET_SERVICE_DEPENDENCIES_TOOL, GET_SERVICES_USED_BY_TOOL, GET_SERVICE_MAP_TOOL}:
        latest_summary["raw_result"] = raw_result
        latest_summary["summary"] = f"Collected topology evidence from {tool_name}."
        scratchpad.setdefault("analysis", {})[tool_name] = raw_result

    elif tool_name in {EXEC_KUBECTL_TOOL, EXEC_SHELL_TOOL}:
        latest_summary["raw_result"] = raw_result
        latest_summary["summary"] = f"Collected direct inspection output from {tool_name}."
        scratchpad.setdefault("analysis", {})[tool_name] = raw_result

    else:
        latest_summary["raw_result"] = raw_result
        latest_summary["summary"] = "Diagnosis tool executed."

    summaries.append(latest_summary)

    state["scratchpad"] = scratchpad
    state["latest_summary"] = latest_summary
    state["collected_summaries"] = summaries
    state["tool_calls_used"] = int(state.get("tool_calls_used", 0)) + 1

    if int(state.get("tool_calls_used", 0)) >= int(state.get("max_tool_calls", MAX_LOGIC_STEPS)):
        state["next_step"] = "end"
        state["final_output"] = {
            "mode": "full_investigation",
            "detection": scratchpad.get("detection", {}),
            "localization": scratchpad.get("localization", {}),
            "analysis": scratchpad.get("analysis", {}),
            "suspected_services": scratchpad.get("suspected_services", []),
            "suspected_pods": scratchpad.get("suspected_pods", []),
            "supporting_summaries": summaries,
            "status": "tool_budget_exhausted",
        }
    else:
        state["next_step"] = "use_tool"

    return state


# -----------------------------------------------------------------------------
# Tool-loop builder
# -----------------------------------------------------------------------------



def build_diagnosis_loop():
    return build_tool_loop(
        agent_fn=diagnosis_agent_node,
        tool_fn=diagnosis_tool_node,
        summarizer_fn=diagnosis_summarizer_node,
    )


# -----------------------------------------------------------------------------
# Outer workflow runner
# -----------------------------------------------------------------------------



def build_diagnosis_scratchpad(state: OuterAgentState) -> Dict[str, Any]:
    detection_lite_result = state.get("detection_lite_result", {})
    return {
        "cluster_context": state.get("cluster_context", {}),
        "backend_status": detection_lite_result.get("backend_status", {}),
        "suspected_services": state.get("suspected_services", []),
        "suspected_pods": state.get("suspected_pods", []),
        "evidence_summary": state.get("evidence_summary", ""),
        "detection": {},
        "localization": {},
        "analysis": {},
    }



def build_diagnosis_goal(state: OuterAgentState) -> str:
    return (
        "Perform a grounded diagnosis pass using the triage output. Prefer service and pod mappings, "
        "log summaries, and metrics first. Use traces only if Jaeger is available and dependency tools "
        "only if Neo4j is available. Use exec_kubectl and exec_shell only as fallback inspection tools."
    )



def run_diagnosis_stage(state: OuterAgentState) -> OuterAgentState:
    loop = build_diagnosis_loop()
    tool_state = build_initial_tool_state(
        user_query=state.get("user_query", ""),
        current_goal=build_diagnosis_goal(state),
        scratchpad=build_diagnosis_scratchpad(state),
        max_tool_calls=8,
    )

    result = loop.invoke(tool_state)
    final_output = result.get("final_output", {})

    state["diagnosis_result"] = {
        "mode": final_output.get("mode", "full_investigation"),
        "detection": final_output.get("detection", {}),
        "localization": final_output.get("localization", {}),
        "analysis": final_output.get("analysis", {}),
        "supporting_summaries": final_output.get("supporting_summaries", []),
        "status": final_output.get("status", "completed_diagnosis_pass"),
    }

    state["suspected_services"] = final_output.get("suspected_services", state.get("suspected_services", []))
    state["suspected_pods"] = final_output.get("suspected_pods", state.get("suspected_pods", []))
    return state
