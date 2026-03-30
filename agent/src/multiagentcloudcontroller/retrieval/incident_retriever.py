from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..graph.routes import should_mark_incident_as_new
from ..graph.state import OuterAgentState
from .chroma_mcp_client import ChromaMCPClient


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
# Chroma MCP integration
# -----------------------------------------------------------------------------


def _normalize_query_results(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    ids = payload.get("ids") or [[]]
    docs = payload.get("documents") or [[]]
    metadatas = payload.get("metadatas") or [[]]
    distances = payload.get("distances") or [[]]

    ranked: List[Dict[str, Any]] = []
    for idx, incident_id in enumerate(ids[0] if ids else []):
        metadata = metadatas[0][idx] if metadatas and metadatas[0] and idx < len(metadatas[0]) else {}
        distance = distances[0][idx] if distances and distances[0] and idx < len(distances[0]) else 1.0
        similarity = max(0.0, min(1.0, 1.0 - float(distance)))
        ranked.append(
            {
                "incident_id": incident_id,
                "title": metadata.get("title", "Historical incident"),
                "summary": docs[0][idx] if docs and docs[0] and idx < len(docs[0]) else "",
                "suspected_faults": list(metadata.get("suspected_faults", [])),
                "suspected_services": list(metadata.get("suspected_services", [])),
                "mitigation_hints": list(metadata.get("mitigation_hints", [])),
                "score": similarity,
                "metadata": metadata,
            }
        )

    return ranked


def query_incident_store(query: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Query incident history through Chroma MCP."""

    query_text = query.get("query_text", "")
    if not query_text:
        return []

    client = ChromaMCPClient()
    try:
        client.ensure_collection()
        payload = client.query_documents(
            query_text=query_text,
            top_k=int(query.get("top_k", DEFAULT_TOP_K)),
            metadata_filter=query.get("metadata_filter") or None,
        )
    except RuntimeError:
        return []

    if not isinstance(payload, dict):
        return []

    return _normalize_query_results(payload)


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
