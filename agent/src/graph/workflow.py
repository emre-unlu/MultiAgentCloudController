from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, START, StateGraph

from .routes import (
    POST_SUPERVISOR_APPROVED,
    POST_SUPERVISOR_FINALIZE,
    POST_SUPERVISOR_REDO,
    ROUTE_DIAGNOSTICS,
    ROUTE_INFORMATION,
    route_after_supervisor,
    route_from_router,
)
from .state import OuterAgentState
from ..reporting.mitigation_report import run_mitigation_report_stage
from ..retrieval.incident_retriever import run_incident_retrieval_stage
from ..retrieval.persistence import run_persistence_stage
from ..subgraphs.runners.detection_lite_runner import run_detection_lite_stage
from ..subgraphs.runners.diagnosis_runner import run_diagnosis_stage
from ..subgraphs.runners.information_runner import run_information_stage
from ..subgraphs.runners.supervisor_runner import run_supervisor_stage


# -------------------------
# Outer workflow nodes
# -------------------------


def router_node(state: OuterAgentState) -> OuterAgentState:
    """Top-level request router.

    Real implementation should classify the incoming request as either:
    - information
    - diagnostics
    """

    state.setdefault("route", ROUTE_DIAGNOSTICS)
    return state



def information_node(state: OuterAgentState) -> OuterAgentState:
    """Handle lightweight informational questions."""

    return run_information_stage(state)



def detection_lite_node(state: OuterAgentState) -> OuterAgentState:
    """Run lightweight triage before retrieval and diagnosis."""

    return run_detection_lite_stage(state)



def incident_retrieval_node(state: OuterAgentState) -> OuterAgentState:
    """Retrieve similar incidents and configure diagnosis mode."""

    return run_incident_retrieval_stage(state)



def diagnosis_node(state: OuterAgentState) -> OuterAgentState:
    """Main diagnosis stage."""

    state["diagnosis_attempts"] = int(state.get("diagnosis_attempts", 0)) + 1
    return run_diagnosis_stage(state)



def supervisor_node(state: OuterAgentState) -> OuterAgentState:
    """Validate diagnosis quality and decide whether to continue or retry."""

    return run_supervisor_stage(state)



def mitigation_report_node(state: OuterAgentState) -> OuterAgentState:
    """Produce final mitigation and reporting output."""

    return run_mitigation_report_stage(state)



def persistence_node(state: OuterAgentState) -> OuterAgentState:
    """Persist incident knowledge when appropriate."""

    return run_persistence_stage(state)


# -------------------------
# Graph builder
# -------------------------


def build_workflow():
    """Build the top-level incident lifecycle graph."""

    builder = StateGraph(OuterAgentState)

    builder.add_node("router", router_node)
    builder.add_node("information", information_node)
    builder.add_node("detection_lite", detection_lite_node)
    builder.add_node("incident_retrieval", incident_retrieval_node)
    builder.add_node("diagnosis", diagnosis_node)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("mitigation_report", mitigation_report_node)
    builder.add_node("persistence", persistence_node)

    builder.add_edge(START, "router")

    builder.add_conditional_edges(
        "router",
        route_from_router,
        {
            ROUTE_INFORMATION: "information",
            ROUTE_DIAGNOSTICS: "detection_lite",
        },
    )

    builder.add_edge("information", END)
    builder.add_edge("detection_lite", "incident_retrieval")
    builder.add_edge("incident_retrieval", "diagnosis")
    builder.add_edge("diagnosis", "supervisor")

    builder.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            POST_SUPERVISOR_APPROVED: "mitigation_report",
            POST_SUPERVISOR_REDO: "diagnosis",
            POST_SUPERVISOR_FINALIZE: "mitigation_report",
        },
    )

    builder.add_edge("mitigation_report", "persistence")
    builder.add_edge("persistence", END)

    return builder.compile()


# -------------------------
# Render helpers
# -------------------------


def try_write_png(compiled_graph, out_path: Path) -> bool:
    try:
        png_bytes = compiled_graph.get_graph().draw_mermaid_png()
        out_path.write_bytes(png_bytes)
        return True
    except Exception as exc:
        print(f"PNG render failed: {exc}")
        return False



def try_write_svg(compiled_graph, out_path: Path) -> bool:
    try:
        draw_fn = getattr(compiled_graph.get_graph(), "draw_mermaid_svg", None)
        if draw_fn is None:
            return False
        svg_text = draw_fn()
        out_path.write_text(svg_text, encoding="utf-8")
        return True
    except Exception as exc:
        print(f"SVG render failed: {exc}")
        return False



def main() -> None:
    output_dir = Path(".")
    graph = build_workflow()

    mermaid_text = graph.get_graph().draw_mermaid()
    mmd_path = output_dir / "workflow_graph.mmd"
    mmd_path.write_text(mermaid_text, encoding="utf-8")

    png_path = output_dir / "workflow_graph.png"
    svg_path = output_dir / "workflow_graph.svg"

    png_ok = try_write_png(graph, png_path)
    svg_ok = try_write_svg(graph, svg_path)

    print("Generated:")
    print(f" - {mmd_path.resolve()}")
    if png_ok:
        print(f" - {png_path.resolve()}")
    if svg_ok:
        print(f" - {svg_path.resolve()}")

    print("\nMermaid preview:\n")
    print(mermaid_text)


if __name__ == "__main__":
    main()
