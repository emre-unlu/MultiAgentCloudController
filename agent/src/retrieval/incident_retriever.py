from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..graph.routes import should_mark_incident_as_new
from ..graph.state import OuterAgentState


DEFAULT_TOP_K = 5
HIGH_CONFIDENCE_THRESHOLD = 0.8
MEDIUM_CONFIDENCE_THRESHOLD = 0.5


# -----------------------------------------------------------------------------
# Query building
# -----------------------------------------------------------------------------


def build_incident_retrieval_query(state: OuterAgentState) -> Dict[str, Any]:
    """Build a Chroma retrieval query from detection-lite output.

    The goal is to turn lightweight triage output into a retrieval-friendly
    incident fingerprint.
    """

    suspected_faults = list(state.get("suspected_faults", []))
    suspected_services = list(state.get("suspected_services", []))
    suspected_pods = list(state.get("suspected_pods", []))
    evidence_summary = state.get("evidence_summary", "")

    query_text_parts: List[str] = []
    if suspected_faults:
        query_text_parts.append("faults: " + ", ".join(suspected_faults))
    if suspected_services:
        query_text_parts.append("services: " + ", ".join(suspected_services))
    if suspected_pods:
        query_text_parts.append("pods: " + ", ".join(suspected_pods))
    if evidence_summary:
        query_text_parts.append("evidence: " + evidence_summary)

    query_text = " | ".join(query_text_parts).strip()
    if not query_text:
        query_text = state.get("user_query", "")

    metadata_filter: Dict[str, Any] = {}
    if suspected_services:
        metadata_filter["suspected_services"] = suspected_services
    if suspected_faults:
        metadata_filter["suspected_faults"] = suspected_faults

    return {
        "query_text": query_text,
        "metadata_filter": metadata_filter,
        "top_k": DEFAULT_TOP_K,
    }


# -----------------------------------------------------------------------------
# Placeholder Chroma MCP integration
# -----------------------------------------------------------------------------


def query_incident_store(query: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Placeholder incident-store lookup.

    Real implementation should call Chroma MCP / ChromaDB and return a ranked
    list of similar incident records.
    """

    query_text = query.get("query_text", "")
    if not query_text:
        return []

    return [
        {
            "incident_id": "placeholder-incident-001",
            "title": "Example historical incident",
            "summary": "Placeholder similar incident returned from the incident store.",
            "suspected_faults": ["unknown_fault"],
            "suspected_services": [],
            "mitigation_hints": ["Inspect recent cluster changes before deeper investigation."],
            "score": 0.62,
            "metadata": {
                "source": "placeholder_chroma_store",
            },
        }
    ]


# -----------------------------------------------------------------------------
# Ranking / confidence helpers
# -----------------------------------------------------------------------------


def select_best_incident_match(
    incidents: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], float]:
    """Select the best retrieved incident and normalize its confidence score."""

    if not incidents:
        return None, 0.0

    ranked = sorted(incidents, key=lambda item: float(item.get("score", 0.0)), reverse=True)
    best_match = ranked[0]
    confidence = float(best_match.get("score", 0.0))
    confidence = max(0.0, min(confidence, 1.0))
    return best_match, confidence



def build_preload_context(best_match: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract reusable context for diagnosis from the best incident match."""

    if not best_match:
        return {}

    return {
        "incident_id": best_match.get("incident_id"),
        "title": best_match.get("title"),
        "summary": best_match.get("summary"),
        "suspected_faults": best_match.get("suspected_faults", []),
        "suspected_services": best_match.get("suspected_services", []),
        "mitigation_hints": best_match.get("mitigation_hints", []),
        "metadata": best_match.get("metadata", {}),
    }



def build_mitigation_hints(best_match: Optional[Dict[str, Any]]) -> List[str]:
    """Extract mitigation hints from the best incident match."""

    if not best_match:
        return []
    return list(best_match.get("mitigation_hints", []))


# -----------------------------------------------------------------------------
# Outer workflow integration
# -----------------------------------------------------------------------------


def run_incident_retrieval_stage(state: OuterAgentState) -> OuterAgentState:
    """Run incident retrieval against the historical incident store.

    This function is intended to replace the placeholder retrieval node in the
    outer workflow.
    """

    query = build_incident_retrieval_query(state)
    incidents = query_incident_store(query)
    best_match, confidence = select_best_incident_match(incidents)

    state["retrieved_incidents"] = incidents
    state["best_incident_match"] = best_match
    state["retrieval_confidence"] = confidence
    state["preload_context"] = build_preload_context(best_match)
    state["mitigation_hints"] = build_mitigation_hints(best_match)

    if confidence >= HIGH_CONFIDENCE_THRESHOLD:
        state["diagnosis_mode"] = "incident_guided"
    else:
        state["diagnosis_mode"] = "full_investigation"

    state["incident_is_new"] = should_mark_incident_as_new(state)
    return state
