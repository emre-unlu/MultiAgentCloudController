from __future__ import annotations

import asyncio
import json
import os
import shlex
from typing import Any, Dict, List, Optional


DEFAULT_COLLECTION = "incident_history"


class ChromaMCPClient:
    """Small wrapper around the Chroma MCP server tools.

    The server is launched over stdio and tools are invoked with the official
    MCP Python client package.
    """

    def __init__(
        self,
        *,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        collection_name: Optional[str] = None,
    ) -> None:
        self.command = command or os.getenv("CHROMA_MCP_COMMAND", "uvx")
        if args is not None:
            self.args = args
        else:
            raw_args = os.getenv("CHROMA_MCP_ARGS", "chroma-mcp")
            self.args = shlex.split(raw_args)
        self.collection_name = collection_name or os.getenv(
            "CHROMA_MCP_COLLECTION", DEFAULT_COLLECTION
        )

    def query_documents(
        self,
        *,
        query_text: str,
        top_k: int,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "collection_name": self.collection_name,
            "query_texts": [query_text],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if metadata_filter:
            payload["where"] = metadata_filter

        return self._run_tool("chroma_query_documents", payload)

    def add_document(self, *, document_id: str, text: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        return self._run_tool(
            "chroma_add_documents",
            {
                "collection_name": self.collection_name,
                "documents": [text],
                "ids": [document_id],
                "metadatas": [metadata],
            },
        )

    def ensure_collection(self) -> None:
        try:
            self._run_tool("chroma_get_collection_info", {"collection_name": self.collection_name})
        except RuntimeError:
            self._run_tool("chroma_create_collection", {"collection_name": self.collection_name})

    def _run_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return asyncio.run(self._run_tool_async(tool_name, arguments))

    async def _run_tool_async(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except Exception as exc:  # pragma: no cover - dependency/runtime guard
            raise RuntimeError(
                "MCP client dependency is missing. Install the `mcp` Python package to use Chroma MCP."
            ) from exc

        server = StdioServerParameters(command=self.command, args=self.args)

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
