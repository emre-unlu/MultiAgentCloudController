from __future__ import annotations

from .state import OuterAgentState


ROUTE_INFORMATION = "information"
ROUTE_DIAGNOSTICS = "diagnostics"

POST_SUPERVISOR_APPROVED = "approved"
POST_SUPERVISOR_REDO = "redo_diagnosis"
POST_SUPERVISOR_FINALIZE = "finalize_with_uncertainty"


def route_from_router(state: OuterAgentState) -> str:
    """Route the request into either the informational or diagnostic path.

    Falls back to the safer lightweight path if the route is missing or invalid.
    """

    route = state.get("route", ROUTE_INFORMATION)
    if route not in {ROUTE_INFORMATION, ROUTE_DIAGNOSTICS}:
        return ROUTE_INFORMATION
    return route


def set_diagnosis_mode_from_retrieval(state: OuterAgentState) -> OuterAgentState:
    """Mutate the state with the diagnosis mode inferred from retrieval confidence.

    High-confidence incident matches allow the diagnosis stage to run in an
    incident-guided mode. Otherwise, the system falls back to a full
    investigation mode.
    """

    confidence = float(state.get("retrieval_confidence", 0.0))
    if confidence >= 0.8:
        state["diagnosis_mode"] = "incident_guided"
    else:
        state["diagnosis_mode"] = "full_investigation"
    return state


def route_after_supervisor(state: OuterAgentState) -> str:
    """Decide whether to approve, retry diagnosis, or finalize with uncertainty.

    Logic:
    - approved -> continue to mitigation/report
    - needs_more_evidence and retries remain -> loop back to diagnosis
    - needs_more_evidence and retries exhausted -> finalize with uncertainty
    - finalize_with_uncertainty -> continue to mitigation/report
    - any unknown verdict -> finalize with uncertainty
    """

    verdict = state.get("supervisor_verdict", "needs_more_evidence")
    attempts = int(state.get("diagnosis_attempts", 0))
    max_attempts = int(state.get("max_diagnosis_attempts", 2))

    if verdict == "approved":
        return POST_SUPERVISOR_APPROVED

    if verdict == "needs_more_evidence":
        if attempts < max_attempts:
            return POST_SUPERVISOR_REDO
        return POST_SUPERVISOR_FINALIZE

    if verdict == "finalize_with_uncertainty":
        return POST_SUPERVISOR_FINALIZE

    return POST_SUPERVISOR_FINALIZE


def should_mark_incident_as_new(state: OuterAgentState) -> bool:
    """Heuristic to decide whether the final incident should be persisted as new.

    Current default behavior:
    - If there was no strong historical match, treat the incident as new.
    - If a match exists but confidence is weak, also treat it as new.
    """

    best_match = state.get("best_incident_match")
    confidence = float(state.get("retrieval_confidence", 0.0))

    if not best_match:
        return True
    return confidence < 0.8
