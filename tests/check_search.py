import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from neoforge_docs_mcp import search  # noqa: E402

QUERIES = [
    ("how to register an item", "current"),
    ("DeferredRegister", "current"),
    ("data components", "current"),
    ("custom armor", "current"),
    ("1.21.1 networking payload", "current"),
    ("screen rendering", "current"),
    ("loot table modifier", "current"),
    ("all versions networking", "all"),
    ("如何注册物品", "current"),
    ("实体数据同步", "current"),
]

for query, version in QUERIES:
    result = search.search(query, version=version, limit=4)
    print("Q:", query, "| v:", result["version"], "| hits:", len(result["hits"]), result.get("note") or "")
    for hit in result["hits"]:
        print("   ", hit["score"], hit["version"], hit["title"], "|", hit["heading"][:60])
    print("    snippet:", (result["hits"][0]["snippet"][:140].replace("\n", " ") if result["hits"] else "-"))
    print()

print("== get_doc ==")
doc = search.get_doc("items/index.md")
print(doc.get("title"), doc.get("url"), len(doc.get("text", "")), "chars", len(doc.get("headings", [])), "headings")

print("== get_section ==")
sec = search.get_section("items/index.md", "creating-an-item")
print(sec.get("heading"), "|", len(sec.get("text", "")), "chars")

print("== find_symbol ==")
for sym in ["DeferredRegister", "Item.Properties#of", "DataComponents"]:
    res = search.find_symbol(sym, limit=3)
    print(sym, "->", [(h["title"], h["version"]) for h in res["hits"]])

print("== list_docs ==")
lst = search.list_docs()
print("pages:", lst["count"], "first:", [p["title"] for p in lst["pages"][:5]])

print("== compare ==")
cmp = search.compare_versions("items/index.md", "1.21.1", "current")
print({k: cmp[k] for k in ("from", "to", "added_lines", "removed_lines") if k in cmp})
print((cmp.get("diff") or cmp.get("error"))[:500])
