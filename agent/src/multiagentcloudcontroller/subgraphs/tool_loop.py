from __future__ import annotations

from typing import Callable

from langgraph.graph import END, START, StateGraph

from ..graph.state import ToolSummaryState


ToolStateNode = Callable[[ToolSummaryState], ToolSummaryState]

STEP_USE_TOOL = "use_tool"
STEP_END = "end"


def agent_node(state: ToolSummaryState) -> ToolSummaryState:
    """Default placeholder agent node.

    Real agent implementations should:
    - inspect the current goal,
    - reason over scratchpad + collected summaries,
    - choose the next tool and its input when needed,
    - set `next_step` to either `use_tool` or `end`,
    - populate `final_output` before ending.

    This placeholder safely stops when the tool budget is exhausted.
    """

    tool_calls_used = int(state.get("tool_calls_used", 0))
    max_tool_calls = int(state.get("max_tool_calls", 5))

    if tool_calls_used >= max_tool_calls:
        state["next_step"] = STEP_END
        state.setdefault("final_output", {})
        return state

    state.setdefault("next_step", STEP_USE_TOOL)
    return state


def use_tool_node(state: ToolSummaryState) -> ToolSummaryState:
    """Default placeholder tool node.

    Real implementations should call the selected tool and store the raw output
    in `latest_tool_result`.
    """

    state.setdefault("latest_tool_result", {})
    return state


def summarize_output_node(state: ToolSummaryState) -> ToolSummaryState:
    """Default placeholder summarizer node.

    Real implementations should transform the raw tool result into a compact,
    structured summary and append it to `collected_summaries`.
    """

    latest_summary = state.get("latest_summary", {})
    summaries = list(state.get("collected_summaries", []))

    if latest_summary:
        summaries.append(latest_summary)

    state["collected_summaries"] = summaries
    state["tool_calls_used"] = int(state.get("tool_calls_used", 0)) + 1
    return state


def route_from_agent(state: ToolSummaryState) -> str:
    """Route from the agent node to either tool use or termination."""

    step = state.get("next_step", STEP_USE_TOOL)
    if step not in {STEP_USE_TOOL, STEP_END}:
        return STEP_USE_TOOL
    return step


def build_tool_loop(
    *,
    agent_fn: ToolStateNode = agent_node,
    tool_fn: ToolStateNode = use_tool_node,
    summarizer_fn: ToolStateNode = summarize_output_node,
):
    """Build a reusable inner execution loop.

    Pattern:
        agent -> use_tool -> summarize_output -> agent

    This loop is intended to be wrapped by outer workflow nodes such as:
    - information runner
    - detection-lite runner
    - diagnosis runner
    - supervisor runner
    """

    builder = StateGraph(ToolSummaryState)

    builder.add_node("agent", agent_fn)
    builder.add_node("use_tool", tool_fn)
    builder.add_node("summarize_output", summarizer_fn)

    builder.add_edge(START, "agent")

    builder.add_conditional_edges(
        "agent",
        route_from_agent,
        {
            STEP_USE_TOOL: "use_tool",
            STEP_END: END,
        },
    )

    builder.add_edge("use_tool", "summarize_output")
    builder.add_edge("summarize_output", "agent")

    return builder.compile()
