from __future__ import annotations

from typing import Any, Dict, List

from ..graph.state import OuterAgentState


DEFAULT_CONFIDENCE = 0.5


def determine_report_status(state: OuterAgentState) -> str:
    """Determine the overall report status from supervisor output."""

    verdict = state.get("supervisor_verdict", "finalize_with_uncertainty")
    if verdict == "approved":
        return "approved"
    if verdict == "needs_more_evidence":
        return "needs_more_evidence"
    return "finalized_with_uncertainty"



def estimate_report_confidence(state: OuterAgentState) -> float:
    """Estimate a simple overall confidence score for the final report.

    Current placeholder logic blends retrieval confidence with a small bonus for
    supervisor approval. This should later be replaced with a better grounded
    scoring strategy based on evidence quality and diagnosis completeness.
    """

    retrieval_confidence = float(state.get("retrieval_confidence", 0.0))
    supervisor_verdict = state.get("supervisor_verdict", "finalize_with_uncertainty")

    confidence = retrieval_confidence if retrieval_confidence > 0 else DEFAULT_CONFIDENCE
    if supervisor_verdict == "approved":
        confidence = min(1.0, confidence + 0.15)
    elif supervisor_verdict == "finalize_with_uncertainty":
        confidence = max(0.0, confidence - 0.15)

    return round(confidence, 3)



def build_supporting_evidence(state: OuterAgentState) -> List[Dict[str, Any]]:
    """Collect compact evidence blocks for the final operator-facing report."""

    evidence: List[Dict[str, Any]] = []

    evidence_summary = state.get("evidence_summary", "")
    if evidence_summary:
        evidence.append(
            {
                "source": "detection_lite",
                "summary": evidence_summary,
            }
        )

    diagnosis_result = state.get("diagnosis_result", {})
    for item in diagnosis_result.get("supporting_summaries", []):
        evidence.append(
            {
                "source": "diagnosis",
                "summary": item,
            }
        )

    best_incident_match = state.get("best_incident_match")
    if best_incident_match:
        evidence.append(
            {
                "source": "incident_history",
                "summary": {
                    "incident_id": best_incident_match.get("incident_id"),
                    "title": best_incident_match.get("title"),
                    "score": state.get("retrieval_confidence", 0.0),
                    "summary": best_incident_match.get("summary", ""),
                },
            }
        )

    return evidence



def build_root_cause_summary(state: OuterAgentState) -> str:
    """Build a concise root-cause summary from diagnosis output."""

    analysis = state.get("diagnosis_result", {}).get("analysis", {})

    probable_root_cause = analysis.get("probable_root_cause")
    if probable_root_cause:
        return str(probable_root_cause)

    best_incident_match = state.get("best_incident_match")
    if best_incident_match:
        return (
            "Root cause not explicitly confirmed yet. Historical retrieval suggests "
            f"similarity to incident '{best_incident_match.get('title', 'unknown')}'."
        )

    return "Root cause not yet confidently established."



def build_mitigation_steps(state: OuterAgentState) -> List[str]:
    """Collect mitigation suggestions for the final report."""

    steps: List[str] = []

    for hint in state.get("mitigation_hints", []):
        if hint and hint not in steps:
            steps.append(str(hint))

    diagnosis_result = state.get("diagnosis_result", {})
    analysis = diagnosis_result.get("analysis", {})
    suggested_actions = analysis.get("suggested_actions", [])
    for action in suggested_actions:
        if action and action not in steps:
            steps.append(str(action))

    if not steps:
        steps.append("Perform a targeted manual review of the affected services and recent changes.")

    return steps



def build_affected_components(state: OuterAgentState) -> Dict[str, List[str]]:
    """Collect the affected services and pods for the final report."""

    localization = state.get("diagnosis_result", {}).get("localization", {})

    services = localization.get("suspected_services", state.get("suspected_services", []))
    pods = localization.get("suspected_pods", state.get("suspected_pods", []))

    return {
        "services": list(services or []),
        "pods": list(pods or []),
    }



def build_report_summary(state: OuterAgentState) -> str:
    """Build a short human-readable incident summary."""

    suspected_faults = state.get("suspected_faults", [])
    affected = build_affected_components(state)

    if suspected_faults or affected["services"] or affected["pods"]:
        return (
            "The system identified a likely Kubernetes incident involving "
            f"fault candidates={suspected_faults}, services={affected['services']}, "
            f"pods={affected['pods']}."
        )

    return "The system completed the diagnostic flow but could not isolate a specific incident signature."



def build_mitigation_report(state: OuterAgentState) -> Dict[str, Any]:
    """Build the final operator-facing mitigation and diagnosis report."""

    return {
        "type": "diagnostic_report",
        "status": determine_report_status(state),
        "confidence": estimate_report_confidence(state),
        "summary": build_report_summary(state),
        "affected_components": build_affected_components(state),
        "root_cause_summary": build_root_cause_summary(state),
        "supporting_evidence": build_supporting_evidence(state),
        "mitigation_steps": build_mitigation_steps(state),
        "supervisor_feedback": state.get("supervisor_feedback", ""),
        "diagnosis_mode": state.get("diagnosis_mode", "full_investigation"),
        "retrieval_confidence": state.get("retrieval_confidence", 0.0),
        "incident_is_new": state.get("incident_is_new", False),
    }



def run_mitigation_report_stage(state: OuterAgentState) -> OuterAgentState:
    """Populate the outer workflow state with the final mitigation report."""

    state["mitigation_report"] = build_mitigation_report(state)
    return state
