"""MCP server exposing the local NeoForge documentation index over stdio."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import search

log = logging.getLogger("neoforge_docs.server")

INSTRUCTIONS = """Local, offline mirror of the NeoForge documentation (docs.neoforged.net).
Covers the current docs (Minecraft 26.1) plus nine archived versions (1.20.4 - 1.21.11),
and the toolchain / user / modpack sections.

How to use it:
1. Call search_docs first. Use ENGLISH keywords, even when the question is in Chinese
   (e.g. 实体同步 -> "entity data sync", 注册 -> "register", 数据生成 -> "data generation").
   Results are section-level snippets; each shows its version and URL.
2. Prefer get_section(doc_id, heading) for the full text of one section. Use get_doc only
   when you need an entire page (it can be long).
3. For a Java/NeoForge API name (DeferredRegister, Item.Properties#of, DataComponents),
   call find_symbol instead of a plain search.
4. Version rule: search_docs defaults to the current version. Pass version="1.21.1" (etc.)
   when the user targets an older Minecraft/NeoForge release, or version="all" to compare.
5. For "what changed between X and Y", call compare_versions.

Answer from the returned text only; cite the URL. If a search returns nothing useful, retry
with fewer, more specific words or mode="api".
"""

server = MCPServer(
    name="neoforge-docs",
    title="NeoForge Documentation",
    version="0.1.0",
    instructions=INSTRUCTIONS,
)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


@server.tool()
def search_docs(
    query: str,
    version: str = "current",
    section: str | None = None,
    limit: int = 6,
    mode: str = "text",
) -> str:
    """Search NeoForge docs and return ranked section snippets with URLs.

    Args:
        query: English keywords, e.g. "register item", "data components", "screen rendering".
        version: "current" (26.1), an exact version such as "1.21.1" / "1.20.4", or "all".
        section: optional filter: "docs", "toolchain", "user", "modpack".
        limit: number of hits, 1-12 (default 6).
        mode: "text" for normal search, "api" to restrict matching to code identifiers.
    """
    return _dumps(search.search(query, version=version, section=section, limit=limit, mode=mode))


@server.tool()
def get_section(doc_id: str, heading: str, version: str = "current") -> str:
    """Return one section (heading + body) of a documentation page.

    Cheaper and more focused than get_doc. The heading argument accepts an anchor
    ("creating-an-item"), a heading title ("Creating an Item"), or any distinctive
    part of the heading path.

    Args:
        doc_id: doc_id from search_docs, or a path such as "items/index.md" / "items".
        heading: anchor, heading text, or heading-path fragment.
        version: version key; only used when doc_id is a path rather than a full doc_id.
    """
    return _dumps(search.get_section(doc_id, heading, version=version))


@server.tool()
def get_doc(doc_id: str, version: str = "current") -> str:
    """Return a whole documentation page as markdown, plus its heading outline.

    Prefer get_section unless the whole page is genuinely needed: pages reach 15k+ chars.

    Args:
        doc_id: doc_id from search_docs, or a path such as "items/index.md" / "items".
        version: version key ("current", "1.21.1", ...) when doc_id is a path.
    """
    return _dumps(search.get_doc(doc_id, version=version))


@server.tool()
def find_symbol(symbol: str, limit: int = 10) -> str:
    """Find where a Java/NeoForge API name is used or explained.

    Exact match first, then substring. Good for "Item.Properties#of", "DeferredRegister",
    "DataComponents", "BlockEntity#saveAdditional".

    Args:
        symbol: the API identifier to look up.
        limit: max hits (1-20, default 10).
    """
    return _dumps(search.find_symbol(symbol, limit=limit))


@server.tool()
def list_docs(version: str = "current", section: str | None = None) -> str:
    """List every page of a documentation version with title, group and URL.

    Useful for browsing or checking whether a page exists before searching.

    Args:
        version: version key ("current", "1.21.1", ...).
        section: optional filter: "docs", "toolchain", "user", "modpack".
    """
    return _dumps(search.list_docs(version=version, section=section))


@server.tool()
def compare_versions(doc: str, from_version: str = "1.21.1", to_version: str = "current") -> str:
    """Diff one documentation page between two versions (migration helper).

    Args:
        doc: page path or doc_id, e.g. "items/index.md".
        from_version: older version key, e.g. "1.21.1".
        to_version: newer version key, e.g. "current".
    """
    return _dumps(search.compare_versions(doc, from_version=from_version, to_version=to_version))


def main() -> int:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="[neoforge-docs] %(levelname)s %(message)s",
    )
    try:
        status = search.ensure_index()
        log.info("index %s", status.get("status"))
    except Exception as exc:  # keep the server alive; tools will report the failure
        log.error("index unavailable: %s", exc)
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
