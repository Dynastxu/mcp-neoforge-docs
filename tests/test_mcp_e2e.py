"""End-to-end MCP stdio smoke test: start the server, list tools, call each one."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)


def show(name: str, text: str, limit: int = 220) -> None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        print(name, "->", text[:limit])
        return
    if "hits" in payload:
        summary = [(h.get("title"), h.get("heading", "")[:40], h.get("version")) for h in payload["hits"][:3]]
        print(name, "->", payload.get("version"), summary)
    elif "pages" in payload:
        print(name, "-> pages:", payload.get("count"), [p["title"] for p in payload["pages"][:3]])
    elif "diff" in payload:
        print(name, "-> +" + str(payload["added_lines"]), "-" + str(payload["removed_lines"]), payload.get("from"), "->", payload.get("to"))
    elif "text" in payload:
        print(name, "->", payload.get("title"), "|", payload.get("heading", ""), "|", len(payload["text"]), "chars")
    else:
        print(name, "->", text[:limit])


async def main() -> int:
    params = StdioServerParameters(
        command=str(PYTHON),
        args=["-m", "neoforge_docs_mcp"],
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            info = await session.initialize()
            print("server:", info.serverInfo.name, info.serverInfo.version)
            print("instructions:", (info.instructions or "")[:60].replace("\n", " "), "...")
            tools = await session.list_tools()
            print("tools:", [t.name for t in tools.tools])

            calls = [
                ("search_docs", {"query": "custom armor", "limit": 2}),
                ("search_docs", {"query": "1.21.1 networking", "limit": 2}),
                ("search_docs", {"query": "如何注册物品", "limit": 2}),
                ("get_section", {"doc_id": "items/index.md", "heading": "creating-an-item"}),
                ("find_symbol", {"symbol": "Item.Properties#of", "limit": 2}),
                ("list_docs", {"section": "user"}),
                ("compare_versions", {"doc": "items/index.md", "from_version": "1.21.1", "to_version": "current"}),
                ("get_doc", {"doc_id": "items/armor.md"}),
            ]
            for name, args in calls:
                result = await session.call_tool(name, args)
                show(name + " " + json.dumps(args, ensure_ascii=False), result.content[0].text)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
