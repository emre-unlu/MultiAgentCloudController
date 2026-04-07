from __future__ import annotations

import json
from typing import Any, Dict
from dotenv import load_dotenv

from .graph.state import build_initial_outer_state
from .graph.workflow import build_workflow

load_dotenv()

DEFAULT_TEST_QUERY = "Investigate why the prometheus-server service in namespace monitoring is failing and users are seeing errors."


def build_demo_cluster_context() -> Dict[str, Any]:
    """Build a small demo cluster context for local smoke testing.

    Replace this with real environment/bootstrap context later if needed.
    """

    return {
        "cluster_name": "demo-cluster",
        "namespace": "default",
        "environment": "local-dev",
    }


def print_section(title: str, payload: Any) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)
    if isinstance(payload, (dict, list)):
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    else:
        print(payload)


def run_workflow(user_query: str = DEFAULT_TEST_QUERY) -> Dict[str, Any]:
    """Run the end-to-end outer workflow for a single query."""

    workflow = build_workflow()
    initial_state = build_initial_outer_state(
        user_query=user_query,
        cluster_context=build_demo_cluster_context(),
        max_diagnosis_attempts=2,
    )

    final_state = workflow.invoke(initial_state)
    return final_state


def main() -> None:
    final_state = run_workflow()

    print_section("Final Mitigation / Information Report", final_state.get("mitigation_report", {}))
    print_section("Persistence Result", final_state.get("persistence_result", {}))
    print_section("Supervisor Verdict", {
        "supervisor_verdict": final_state.get("supervisor_verdict"),
        "supervisor_feedback": final_state.get("supervisor_feedback"),
    })
    print_section("Diagnosis Result", final_state.get("diagnosis_result", {}))
    print_section("Retrieved Incidents", final_state.get("retrieved_incidents", []))
    print_section("Final Workflow State", final_state)


if __name__ == "__main__":
    main()
