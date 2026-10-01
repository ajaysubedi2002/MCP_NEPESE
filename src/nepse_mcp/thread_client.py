from __future__ import annotations

from typing import Any
from uuid import uuid4

from langsmith import traceable


class ThreadedMCPClient:
    """Attach one stable LangSmith thread ID to every MCP request."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.thread_id = str(uuid4())

    def start_new_thread(self) -> str:
        """Start a new LangSmith thread while keeping the MCP connection."""
        self.thread_id = str(uuid4())
        return self.thread_id

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Call a tool with this client's thread metadata."""
        request_meta = dict(kwargs.pop("meta", {}) or {})
        request_meta["thread_id"] = self.thread_id
        return await self.client.call_tool(
            name,
            arguments,
            meta=request_meta,
            **kwargs,
        )

    async def run_chat_turn(self, user_query: str) -> Any:
        """Trace a user query and route it through the MCP server."""

        @traceable(name="chat_turn", run_type="chain")
        async def chat_turn(query: str) -> Any:
            return await self.call_tool(
                "route_and_process_request",
                {"user_query": query},
            )

        return await chat_turn(
            user_query,
            langsmith_extra={"metadata": {"thread_id": self.thread_id}},
        )

    async def __aenter__(self) -> "ThreadedMCPClient":
        await self.client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.client.__aexit__(exc_type, exc_value, traceback)