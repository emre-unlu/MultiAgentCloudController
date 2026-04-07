from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypeAlias

from pydantic import BaseModel, Field


ToolInputValue: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | List[str]
    | List[int]
    | List[float]
    | List[bool]
)


# -----------------------------------------------------------------------------
# Tool-loop schemas
# -----------------------------------------------------------------------------


class ToolArgument(BaseModel):
    """Represents one tool call candidate."""

    name: str = Field(..., description="Tool name exposed by the MCP server.")
    arguments: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments that will be passed to the selected tool.",
    )


class ToolDecision(BaseModel):
    """Structured output for one inner-loop decision step."""

    selected_tool: Optional[str] = Field(
        default=None,
        description="The next tool to call. Use null when next_step='end'.",
    )
    tool_input: Dict[str, ToolInputValue] = Field(
        default_factory=dict,
        description="Arguments for the selected tool.",
    )
    next_step: Literal["use_tool", "end"] = Field(
        ...,
        description="Whether the loop should execute another tool call or stop.",
    )
    rationale: str = Field(
        ...,
        description="Short explanation for why this tool was chosen or why the loop should end.",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Model confidence in the current decision.",
    )


class ToolSummary(BaseModel):
    """Compact summary of one completed tool call."""

    tool_name: str = Field(..., description="Name of the tool that was executed.")
    summary: str = Field(..., description="Compact human-readable summary of the tool result.")
    key_findings: List[str] = Field(
        default_factory=list,
        description="Short bullet-style findings extracted from the tool output.",
    )
    suspected_services: List[str] = Field(
        default_factory=list,
        description="Service names implicated by the result, if any.",
    )
    suspected_pods: List[str] = Field(
        default_factory=list,
        description="Pod names implicated by the result, if any.",
    )
    suspected_faults: List[str] = Field(
        default_factory=list,
        description="Fault candidates inferred from the result, if any.",
    )
    raw_result_excerpt: Optional[str] = Field(
        default=None,
        description="Optional short excerpt from the raw result for traceability.",
    )


class AgentContext(BaseModel):
    """Normalized context sent into the LLM decision layer."""

    role: Literal["information", "detection_lite", "diagnosis", "supervisor"] = Field(
        ...,
        description="Which agent is making the decision.",
    )
    user_query: str = Field(..., description="Original user query.")
    current_goal: str = Field(..., description="Current stage-specific goal.")
    allowed_tools: List[str] = Field(
        default_factory=list,
        description="Tool names this agent is allowed to choose from right now.",
    )
    backend_status: Dict[str, Any] = Field(
        default_factory=dict,
        description="Current backend availability snapshot.",
    )
    scratchpad: Dict[str, Any] = Field(
        default_factory=dict,
        description="Stage-local working memory.",
    )
    prior_summaries: List[ToolSummary] = Field(
        default_factory=list,
        description="Summaries of prior tool calls in the current loop.",
    )
    max_tool_calls: int = Field(
        default=5,
        ge=1,
        description="Maximum number of tool calls allowed for the current stage.",
    )
    tool_calls_used: int = Field(
        default=0,
        ge=0,
        description="Number of tool calls already used in the current stage.",
    )


# -----------------------------------------------------------------------------
# Investigation schemas
# -----------------------------------------------------------------------------


class Symptom(BaseModel):
    """A symptom observed during investigation."""

    potential_symptom: str = Field(..., description="Type of symptom observed.")
    resource_type: Literal["pod", "service", "cluster", "trace", "metric"] = Field(
        ...,
        description="Type of resource experiencing the issue.",
    )
    affected_resource: str = Field(
        ...,
        description="Exact resource name experiencing the issue.",
    )
    evidence: str = Field(
        ...,
        description="Evidence supporting this symptom identification.",
    )


class SymptomList(BaseModel):
    """Collection of observed symptoms."""

    symptoms: List[Symptom] = Field(
        default_factory=list,
        description="List of symptoms observed in the investigation.",
    )


class InvestigationTask(BaseModel):
    """A diagnosis task the agent may perform."""

    priority: int = Field(..., description="Execution order for this investigation task.")
    status: Literal["pending", "in_progress", "completed"] = Field(
        default="pending",
        description="Status of the investigation task.",
    )
    investigation_goal: str = Field(..., description="Goal of the investigation.")
    target_resource: str = Field(..., description="Name of the resource to investigate.")
    resource_type: Literal["pod", "service", "namespace", "cluster"] = Field(
        ...,
        description="Type of resource being investigated.",
    )
    suggested_tools: List[str] = Field(
        default_factory=list,
        description="Tools suggested for the investigation.",
    )


class InvestigationTaskList(BaseModel):
    """Collection of investigation tasks."""

    investigation_tasks: List[InvestigationTask] = Field(
        default_factory=list,
        description="List of investigation tasks to be performed.",
    )


class RCAAgentExplanation(BaseModel):
    """Aggregates reasoning steps and insights from the diagnosis stage."""

    steps: List[str] = Field(
        default_factory=list,
        description="Chronological list of actions or analyses performed.",
    )
    insights: List[str] = Field(
        default_factory=list,
        description="Key findings or insights discovered during the investigation.",
    )


# -----------------------------------------------------------------------------
# Reporting schemas
# -----------------------------------------------------------------------------


class FinalReport(BaseModel):
    """Final root-cause and incident report."""

    root_cause: str = Field(..., description="Identified root cause of the incident.")
    affected_resources: List[str] = Field(
        default_factory=list,
        description="Resources affected by the incident.",
    )
    evidence_summary: str = Field(
        ...,
        description="Summary of evidence collected across the investigation.",
    )
    investigation_summary: str = Field(
        ...,
        description="Overview of the investigation process and findings.",
    )
    detection: bool = Field(
        ...,
        description="Whether a problem was detected in the cluster.",
    )
    localization: Optional[List[str]] = Field(
        default=None,
        description="List of faulty components identified as likely root cause targets.",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in the final diagnosis.",
    )
    mitigation_steps: List[str] = Field(
        default_factory=list,
        description="Suggested mitigation or next-action steps.",
    )


class SupervisorDecision(BaseModel):
    """Supervisor decision to conclude or continue investigation."""

    verdict: Literal["approved", "needs_more_evidence", "finalize_with_uncertainty"] = Field(
        ...,
        description="Supervisor decision on the current investigation state.",
    )
    feedback: str = Field(
        ...,
        description="Short explanation for the supervisor verdict.",
    )
    missing_evidence: List[str] = Field(
        default_factory=list,
        description="Specific evidence gaps that remain, if any.",
    )
    final_report: Optional[FinalReport] = Field(
        default=None,
        description="Final root-cause report when evidence is sufficient.",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Supervisor confidence in the verdict.",
    )


class EvaluationResult(BaseModel):
    """Evaluation result for a diagnosis or report."""

    score: int = Field(
        ...,
        ge=1,
        le=5,
        description="Numeric evaluation score from 1 to 5.",
    )
    reasoning: str = Field(
        ...,
        description="Very short reasoning for the assigned score.",
    )