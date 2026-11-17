"""Start the real server over stdio and call it the way Claude Desktop or Claude Code would."""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _run(staging: str) -> tuple[list[str], dict]:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "po_intake.server"],
        env={**os.environ, "PO_STAGING_DIR": staging, "PO_LLM": "off"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = [t.name for t in (await session.list_tools()).tools]
            res = await session.call_tool("process_inbox", {})
            return tools, json.loads(res.content[0].text)


def test_server_over_stdio(tmp_path):
    tools, result = asyncio.run(_run(str(tmp_path / "staging")))
    assert {"list_inbox", "process_inbox", "list_exceptions", "approve_order", "metrics"} <= set(tools)
    assert result["metrics"]["by_status"] == {"draft": 1, "exception": 4, "ignored": 1}
