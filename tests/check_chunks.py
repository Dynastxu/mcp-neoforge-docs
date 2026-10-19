"""Ad-hoc chunk quality check over a few representative documents."""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from neoforge_docs_mcp.chunk import build_chunks  # noqa: E402
from neoforge_docs_mcp.config import docs_root  # noqa: E402
from neoforge_docs_mcp.parse import parse_doc  # noqa: E402

REL = [
    "items/index.md",
    "concepts/events.md",
    "resources/client/models/items.md",
    "gettingstarted/index.md",
    "resources/server/loottables/index.md",
]

sizes: list[int] = []
for rel in REL:
    d = parse_doc(docs_root() / "docs" / rel, rel)
    chunks = build_chunks(d.title, d.body)
    sizes.extend(c.n_tokens for c in chunks)
    print(rel, "->", len(chunks), "chunks", [c.n_tokens for c in chunks][:10])
    for c in chunks[:3]:
        print("   ", c.anchor or "(root)", "|", c.heading_path[:80])

print("avg", round(statistics.mean(sizes)), "max", max(sizes), "min", min(sizes))
