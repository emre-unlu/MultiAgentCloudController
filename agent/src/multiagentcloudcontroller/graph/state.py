from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict


RouteType = Literal["information", "diagnostics"]
DiagnosisMode = Literal["incident_guided", "full_investigation"]
SupervisorVerdict = Literal[
    "approved",
    "needs_more_evidence",
    "finalize_with_uncertainty",
]
NextToolStep = Literal["use_tool", "end"]


class OuterAgentState(TypedDict, total=False):
    """Top-level workflow state for the incident lifecycle graph.

    This state is shared across the outer LangGraph workflow and stores
    durable information for the whole request, from routing to persistence.
    """

    # Request / routing
    user_query: str
    route: RouteType

    # Shared operational context
    cluster_context: Dict[str, Any]

    # Detection-lite outputs
    detection_lite_result: Dict[str, Any]
    suspected_faults: List[str]
    suspected_services: List[str]
    suspected_pods: List[str]
    evidence_summary: str

    # Incident retrieval outputs
    retrieved_incidents: List[Dict[str, Any]]
    best_incident_match: Optional[Dict[str, Any]]
    retrieval_confidence: float
    preload_context: Dict[str, Any]
    mitigation_hints: List[str]
    diagnosis_mode: DiagnosisMode

    # Main diagnosis stage output
    diagnosis_result: Dict[str, Any]
    diagnosis_attempts: int
    max_diagnosis_attempts: int

    # Supervisor output
    supervisor_verdict: SupervisorVerdict
    supervisor_feedback: str

    # Final response / knowledge handling
    mitigation_report: Dict[str, Any]
    incident_is_new: bool
    persistence_result: Dict[str, Any]


class ToolSummaryState(TypedDict, total=False):
    """Reusable inner-loop state for token-efficient agent execution.

    This state is intended for subgraphs that follow the pattern:

        agent -> use_tool -> summarize_output -> agent

    The goal is to keep raw tool outputs out of the agent's long-term context
    and instead reason over compact structured summaries.
    """

    # Goal / task framing for the current runner
    user_query: str
    current_goal: str

    # Optional agent-local working memory
    scratchpad: Dict[str, Any]

    # Tool availability / LLM decision support
    allowed_tools: List[str]
    latest_rationale: str
    latest_decision_confidence: float

    # Tool invocation state
    selected_tool: Optional[str]
    tool_input: Dict[str, Any]
    latest_tool_result: Dict[str, Any]
    latest_summary: Dict[str, Any]
    collected_summaries: List[Dict[str, Any]]

    # Budgeting / stopping control
    tool_calls_used: int
    max_tool_calls: int
    next_step: NextToolStep

    # Final structured output for the outer workflow node
    final_output: Dict[str, Any]


def build_initial_outer_state(
    user_query: str,
    *,
    cluster_context: Optional[Dict[str, Any]] = None,
    max_diagnosis_attempts: int = 2,
) -> OuterAgentState:
    """Create a safe initial outer workflow state.

    Args:
        user_query: The original user request.
        cluster_context: Optional cluster/environment context already known.
        max_diagnosis_attempts: Maximum number of diagnosis retries allowed
            after supervisor review.
    """

    return OuterAgentState(
        user_query=user_query,
        route="diagnostics",
        cluster_context=cluster_context or {},
        suspected_faults=[],
        suspected_services=[],
        suspected_pods=[],
        evidence_summary="",
        retrieved_incidents=[],
        best_incident_match=None,
        retrieval_confidence=0.0,
        preload_context={},
        mitigation_hints=[],
        diagnosis_mode="full_investigation",
        diagnosis_result={},
        diagnosis_attempts=0,
        max_diagnosis_attempts=max_diagnosis_attempts,
        supervisor_verdict="needs_more_evidence",
        supervisor_feedback="",
        mitigation_report={},
        incident_is_new=False,
        persistence_result={},
    )


def build_initial_tool_state(
    user_query: str,
    current_goal: str,
    *,
    scratchpad: Optional[Dict[str, Any]] = None,
    max_tool_calls: int = 5,
) -> ToolSummaryState:
    """Create a safe initial inner-loop state.

    Args:
        user_query: The original user request.
        current_goal: The current agent-stage objective.
        scratchpad: Optional stage-specific context passed from the outer graph.
        max_tool_calls: Maximum number of tools the agent may invoke during
            this inner execution loop.
    """

    return ToolSummaryState(
        user_query=user_query,
        current_goal=current_goal,
        scratchpad=scratchpad or {},
        selected_tool="",
        tool_input={},
        latest_tool_result={},
        latest_summary={},
        collected_summaries=[],
        tool_calls_used=0,
        max_tool_calls=max_tool_calls,
        next_step="use_tool",
        final_output={},
    )
