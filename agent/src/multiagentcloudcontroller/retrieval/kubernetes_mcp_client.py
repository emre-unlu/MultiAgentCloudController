from __future__ import annotations

import asyncio
import json
import os
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class KubernetesMCPClient:
    """Small wrapper around a Kubernetes MCP server."""

    def __init__(
        self,
        *,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        repo_path: Optional[str] = None,
    ) -> None:
        self.command = command or os.getenv("KUBERNETES_MCP_COMMAND", "python")
        if args is not None:
            self.args = args
        else:
            raw_args = os.getenv("KUBERNETES_MCP_ARGS", "main.py")
            self.args = shlex.split(raw_args)

        self.repo_path = repo_path or os.getenv("KUBERNETES_MCP_REPO_PATH")

    def call_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return asyncio.run(self._call_tool_async(tool_name, arguments or {}))

    async def _call_tool_async(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except Exception as exc:
            raise RuntimeError(
                "MCP client dependency is missing. Install the `mcp` Python package to use Kubernetes MCP."
            ) from exc

        env = dict(os.environ)
        env.pop("VIRTUAL_ENV", None)
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONPATH", None)

        kwargs: Dict[str, Any] = {
            "command": self.command,
            "args": self.args,
            "env": env,
        }

        if self.repo_path:
            repo = Path(self.repo_path)
            if not repo.exists() or not repo.is_dir():
                raise RuntimeError(
                    f"Invalid KUBERNETES_MCP_REPO_PATH: {self.repo_path!r}"
                )
            kwargs["cwd"] = str(repo)

        if os.getenv("DEBUG", "false").lower() == "true":
            logger.info(
                "K8s MCP launch: %s",
                {
                    "command": kwargs.get("command"),
                    "args": kwargs.get("args"),
                    "cwd": kwargs.get("cwd"),
                },
            )

        server = StdioServerParameters(**kwargs)

        try:
            async with stdio_client(server) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments=arguments)
        except Exception as exc:
            raise RuntimeError(
                f"Kubernetes MCP tool call failed for '{tool_name}' with arguments={arguments!r}: {exc}"
            ) from exc

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
            parsed = json.loads(combined)
            if isinstance(parsed, dict):
                return parsed
            return {"parsed": parsed}
        except json.JSONDecodeError:
            return {"raw": combined}