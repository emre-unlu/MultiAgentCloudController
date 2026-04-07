from pathlib import Path
import json

from dotenv import load_dotenv

project_root = Path(__file__).resolve().parents[1]
load_dotenv(project_root / ".env")

from multiagentcloudcontroller.retrieval.kubernetes_mcp_client import KubernetesMCPClient


def print_title(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def pretty(data, max_len: int = 4000) -> str:
    text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    if len(text) > max_len:
        return text[:max_len] + "\n... [truncated]"
    return text


def print_result(title: str, data) -> None:
    print_title(title)
    print(pretty(data))


def compact_backend_status(data: dict) -> dict:
    return {
        "kubernetes": data.get("kubernetes"),
        "prometheus": data.get("prometheus"),
        "jaeger": data.get("jaeger"),
        "neo4j": data.get("neo4j"),
    }


def compact_cluster_overview(data: dict) -> dict:
    return {
        "namespace": data.get("namespace"),
        "pod_count": data.get("pod_count"),
        "service_count": data.get("service_count"),
        "service_names": [svc.get("name") for svc in data.get("services", []) if isinstance(svc, dict)],
        "pod_names": [
            pod.get("name") if isinstance(pod, dict) else pod
            for pod in data.get("pods", [])
        ],
    }


def compact_shell_result(data: dict) -> dict:
    return {
        "command": data.get("command"),
        "exit_code": data.get("exit_code"),
        "success": data.get("success"),
        "timed_out": data.get("timed_out"),
        "stdout": data.get("stdout"),
        "stderr": data.get("stderr"),
    }


def main() -> None:
    client = KubernetesMCPClient()

    backend = client.call_tool("get_backend_status", {})
    print_result("Backend Status", compact_backend_status(backend))

    overview = client.call_tool("get_cluster_overview", {"namespace": "default"})
    print_result("Cluster Overview", compact_cluster_overview(overview))

    shell_policy = client.call_tool("get_shell_policy", {})
    print_result("Shell Policy", shell_policy)

    shell_result = client.call_tool("exec_shell", {"command": "kubectl get ns"})
    print_result("exec_shell: kubectl get ns", compact_shell_result(shell_result))

    kubectl_result = client.call_tool("exec_kubectl", {"command": "get ns"})
    print_result("exec_kubectl: get ns", compact_shell_result(kubectl_result))


if __name__ == "__main__":
    main()