from __future__ import annotations

import asyncio
import json
import os
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class KubernetesMCPClient:
    """Small wrapper around a Kubernetes MCP server.

    The server is launched over stdio and tools are invoked with the official
    MCP Python client package.
    """

    def __init__(
        self,
        *,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        repo_path: Optional[str] = None,
    ) -> None:
        self.command = command or os.getenv("KUBERNETES_MCP_COMMAND", "poetry")
        if args is not None:
            self.args = args
        else:
            raw_args = os.getenv("KUBERNETES_MCP_ARGS", "run python main.py")
            self.args = shlex.split(raw_args)

        self.repo_path = repo_path or os.getenv("KUBERNETES_MCP_REPO_PATH")

    def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return asyncio.run(self._call_tool_async(tool_name, arguments or {}))

    def _resolve_server_command(self) -> Tuple[str, List[str]]:
        if not self.repo_path:
            return self.command, self.args

        repo = Path(self.repo_path)
        if not repo.exists() or not repo.is_dir():
            raise RuntimeError(
                "Kubernetes MCP repository path is invalid. "
                f"Set KUBERNETES_MCP_REPO_PATH to an existing directory (current: {self.repo_path!r})."
            )

        launch_command = shlex.join([self.command, *self.args])
        return "bash", ["-lc", f"cd {shlex.quote(str(repo))} && {launch_command}"]

    async def _call_tool_async(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except Exception as exc:  # pragma: no cover - dependency/runtime guard
            raise RuntimeError(
                "MCP client dependency is missing. Install the `mcp` Python package to use Kubernetes MCP."
            ) from exc

        server_command, server_args = self._resolve_server_command()
        server = StdioServerParameters(command=server_command, args=server_args)

        async with stdio_client(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
                content = getattr(result, "content", None)
                if not content:
                    return {}

                text_chunks: List[str] = []
                for chunk in content:
                    chunk_text = getattr(chunk, "text", None)
                    if chunk_text:
                        text_chunks.append(chunk_text)

                if not text_chunks:
                    return {}

                combined = "\n".join(text_chunks)
                try:
                    return json.loads(combined)
                except json.JSONDecodeError:
                    return {"raw": combined}
