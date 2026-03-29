from __future__ import annotations

from typing import Any, Dict
from uuid import uuid4

from ..graph.state import OuterAgentState
from .chroma_mcp_client import ChromaMCPClient


# -----------------------------------------------------------------------------
# Incident document building
# -----------------------------------------------------------------------------


def build_incident_document(state: OuterAgentState) -> Dict[str, Any]:
    """Build a structured incident document for persistence.

    This document is intended to be stored in the incident-history layer
    (eventually through Chroma MCP / ChromaDB).
    """

    diagnosis_result = state.get("diagnosis_result", {})
    mitigation_report = state.get("mitigation_report", {})

    return {
        "user_query": state.get("user_query", ""),
        "diagnosis_mode": state.get("diagnosis_mode", "full_investigation"),
        "suspected_faults": list(state.get("suspected_faults", [])),
        "suspected_services": list(state.get("suspected_services", [])),
        "suspected_pods": list(state.get("suspected_pods", [])),
        "evidence_summary": state.get("evidence_summary", ""),
        "diagnosis_result": diagnosis_result,
        "mitigation_report": mitigation_report,
        "supervisor_verdict": state.get("supervisor_verdict", "finalize_with_uncertainty"),
        "supervisor_feedback": state.get("supervisor_feedback", ""),
        "retrieval_confidence": float(state.get("retrieval_confidence", 0.0)),
        "best_incident_match": state.get("best_incident_match"),
    }


# -----------------------------------------------------------------------------
# Chroma MCP persistence backend
# -----------------------------------------------------------------------------


def persist_incident_document(document: Dict[str, Any]) -> Dict[str, Any]:
    """Persist incident knowledge through Chroma MCP."""

    client = ChromaMCPClient()
    document_id = f"incident-{uuid4()}"

    metadata = {
        "title": "Kubernetes incident",
        "suspected_faults": document.get("suspected_faults", []),
        "suspected_services": document.get("suspected_services", []),
        "mitigation_hints": (document.get("mitigation_report") or {}).get("suggested_actions", []),
        "retrieval_confidence": document.get("retrieval_confidence", 0.0),
    }

    try:
        client.ensure_collection()
        client.add_document(
            document_id=document_id,
            text=document.get("evidence_summary", "") or document.get("user_query", ""),
            metadata=metadata,
        )
    except RuntimeError as exc:
        return {
            "status": "failed",
            "stored": False,
            "error": str(exc),
            "document_id": document_id,
        }

    return {
        "status": "persisted",
        "stored": True,
        "document_id": document_id,
        "document_preview": {
            "user_query": document.get("user_query", ""),
            "suspected_faults": document.get("suspected_faults", []),
        },
    }


# -----------------------------------------------------------------------------
# Outer workflow integration
# -----------------------------------------------------------------------------


def should_persist_incident(state: OuterAgentState) -> bool:
    """Decide whether the current incident should be persisted.

    Default behavior:
    - persist only for diagnostic flows,
    - persist only if the system currently believes the incident is new.
    """

    mitigation_report = state.get("mitigation_report", {})
    report_type = mitigation_report.get("type")

    if report_type == "information_response":
        return False

    return bool(state.get("incident_is_new", False))



def run_persistence_stage(state: OuterAgentState) -> OuterAgentState:
    """Persist incident knowledge when appropriate."""

    if not should_persist_incident(state):
        state["persistence_result"] = {
            "status": "skipped",
            "stored": False,
            "reason": "Incident was not marked as new or the flow was informational.",
        }
        return state

    document = build_incident_document(state)
    result = persist_incident_document(document)
    state["persistence_result"] = result
    return state
