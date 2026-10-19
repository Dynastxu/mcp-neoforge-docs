"""In-process check of tool registration, schemas and execution (no subprocess)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from neoforge_docs_mcp.server import server  # noqa: E402


async def main() -> int:
    tools = await server.list_tools()
    print("tools:", len(tools))
    for tool in tools:
        schema = tool.input_schema or {}
        required = schema.get("required", [])
        props = list(schema.get("properties", {}).keys())
        print(" -", tool.name, "| required:", required, "| args:", props)

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
        result = await server.call_tool(name, args)
        text = result.content[0].text
        payload = json.loads(text)
        if "hits" in payload:
            summary = [(h["title"], h["heading"][:38], h["version"]) for h in payload["hits"][:2]]
            print(name, json.dumps(args, ensure_ascii=False), "->", payload.get("version"), summary)
        elif "pages" in payload:
            print(name, "-> pages:", payload["count"], [p["title"] for p in payload["pages"][:3]])
        elif "diff" in payload:
            print(name, "-> +" + str(payload["added_lines"]), "-" + str(payload["removed_lines"]),
                  payload.get("from"), "->", payload.get("to"))
        else:
            print(name, "->", payload.get("title"), "|", payload.get("heading", ""), "|", len(payload.get("text", "")), "chars")

    # error paths
    missing = await server.call_tool("get_doc", {"doc_id": "does/not/exist.md"})
    print("missing doc ->", json.loads(missing.content[0].text).get("error"))
    bad_sym = await server.call_tool("find_symbol", {"symbol": "TotallyBogusSymbolName"})
    print("bogus symbol ->", json.loads(bad_sym.content[0].text).get("count"))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
