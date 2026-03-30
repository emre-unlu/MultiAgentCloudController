from dotenv import load_dotenv
load_dotenv()

from multiagentcloudcontroller.retrieval.kubernetes_mcp_client import KubernetesMCPClient

client = KubernetesMCPClient()
print(client.call_tool("get_backend_status", {}))
print(client.call_tool("get_cluster_overview", {"namespace": "default"}))