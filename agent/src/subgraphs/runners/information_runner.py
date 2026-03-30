from __future__ import annotations

from typing import Any, Dict

from ...graph.state import OuterAgentState, ToolSummaryState, build_initial_tool_state
from ...retrieval.kubernetes_mcp_client import KubernetesMCPClient
from ..tool_loop import build_tool_loop


# -----------------------------------------------------------------------------
# Placeholder inner-loop node implementations for the information stage
# -----------------------------------------------------------------------------


INFORMATION_TOOL_NAME = "information_lookup"


def information_agent_node(state: ToolSummaryState) -> ToolSummaryState:
    """Reasoning node for the information stage.

    Real implementation should:
    - interpret the informational request,
    - choose a small number of relevant MCP tools if needed,
    - avoid deep diagnostic behavior,
    - produce a concise structured answer for the outer workflow.

    Current placeholder behavior:
    - if the tool budget is exhausted, stop with a minimal informational result
    - otherwise, request a single lightweight information-oriented tool
    - when only one tool call remains, warn the agent to summarize clearly
    """

    tool_calls_used = int(state.get("tool_calls_used", 0))
    max_tool_calls = int(state.get("max_tool_calls", 2))

    if tool_calls_used >= max_tool_calls:
        state["next_step"] = "end"
        state["final_output"] = {
            "answer": "Information request ended because the tool budget was exhausted.",
            "supporting_summaries": state.get("collected_summaries", []),
            "status": "tool_budget_exhausted",
        }
        return state

    tool_calls_remaining = max_tool_calls - tool_calls_used
    if tool_calls_remaining == 1:
        state["current_goal"] = (
            f"{state.get('current_goal', '')} Only one tool call remains. Use the final "
            "tool call carefully and be ready to summarize the answer clearly "
            "after this step."
        ).strip()

    state["selected_tool"] = INFORMATION_TOOL_NAME
    state["tool_input"] = {
        "user_query": state.get("user_query", ""),
        "cluster_context": state.get("scratchpad", {}).get("cluster_context", {}),
    }
    state["next_step"] = "use_tool"
    return state



def information_tool_node(state: ToolSummaryState) -> ToolSummaryState:
    """Execute the selected Kubernetes MCP tool for the information stage."""

    selected_tool = state.get("selected_tool", INFORMATION_TOOL_NAME)
    tool_input = state.get("tool_input", {})

    client = KubernetesMCPClient()
    try:
        raw_result = client.call_tool(selected_tool, tool_input)
    except RuntimeError as exc:
        raw_result = {
            "error": str(exc),
            "message": "Information tool execution failed.",
        }

    state["latest_tool_result"] = {
        "tool_name": selected_tool,
        "tool_input": tool_input,
        "raw_result": raw_result,
    }
    return state



def information_summarizer_node(state: ToolSummaryState) -> ToolSummaryState:
    """Placeholder summarizer node for the information stage.

    This node runs after every tool use and compresses the raw tool output into
    a concise answer-oriented summary.
    """

    latest_tool_result = state.get("latest_tool_result", {})
    raw_result = latest_tool_result.get("raw_result", {})

    latest_summary = {
        "tool_name": latest_tool_result.get("tool_name", INFORMATION_TOOL_NAME),
        "summary": raw_result.get("message")
        or raw_result.get("raw")
        or "No informational details returned by tool.",
    }

    summaries = list(state.get("collected_summaries", []))
    summaries.append(latest_summary)

    state["latest_summary"] = latest_summary
    state["collected_summaries"] = summaries
    state["tool_calls_used"] = int(state.get("tool_calls_used", 0)) + 1

    # Placeholder stopping rule: one summarized information pass is enough.
    state["next_step"] = "end"
    state["final_output"] = {
        "answer": latest_summary.get("summary", ""),
        "supporting_summaries": summaries,
        "status": "completed_information_response",
    }
    return state


# -----------------------------------------------------------------------------
# Tool-loop builder for the information stage
# -----------------------------------------------------------------------------


def build_information_loop():
    """Build the reusable inner tool loop for informational requests."""

    return build_tool_loop(
        agent_fn=information_agent_node,
        tool_fn=information_tool_node,
        summarizer_fn=information_summarizer_node,
    )


# -----------------------------------------------------------------------------
# Outer workflow runner
# -----------------------------------------------------------------------------


def build_information_scratchpad(state: OuterAgentState) -> Dict[str, Any]:
    """Extract information-relevant context from the outer workflow state."""

    return {
        "cluster_context": state.get("cluster_context", {}),
        "retrieved_incidents": state.get("retrieved_incidents", []),
    }



def build_information_goal(state: OuterAgentState) -> str:
    """Create a stage-specific objective for the information loop."""

    return (
        "Answer the user's informational Kubernetes or observability question "
        "concisely and safely. Use tools only if needed, avoid deep incident "
        "diagnosis, and summarize the result clearly."
    )



def run_information_stage(state: OuterAgentState) -> OuterAgentState:
    """Run the information stage as an inner reusable tool-summary loop."""

    loop = build_information_loop()
    tool_state = build_initial_tool_state(
        user_query=state.get("user_query", ""),
        current_goal=build_information_goal(state),
        scratchpad=build_information_scratchpad(state),
        max_tool_calls=2,
    )

    result = loop.invoke(tool_state)
    state["mitigation_report"] = {
        "type": "information_response",
        **result.get("final_output", {}),
    }
    return state
