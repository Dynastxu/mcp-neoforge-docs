"""Query layer: search, page/section retrieval, symbol lookup, version diffs."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from . import config
from .parse import slugify

MAX_LIMIT = 12
DEFAULT_LIMIT = 6
SNIPPET_CHARS = 620

TOKEN_RE = re.compile(r"[A-Za-z0-9_+#]+")
CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")
VERSION_RE = re.compile(r"\b(1\.(?:20|21)\.\d{1,2}|26\.\d{1,2})\b")

STOP = {
    "the", "a", "an", "how", "to", "do", "i", "in", "of", "for", "and", "or", "is",
    "are", "can", "with", "on", "my", "me", "it", "this", "that", "what", "when",
    "where", "which", "using", "use", "make", "get", "set", "be", "should", "need",
    "all", "any", "version", "versions", "docs", "documentation", "latest", "please",
    "explain", "show", "find", "tell", "want", "about", "into", "from", "does",
}

ZH_TERMS = {
    "物品": "item", "方块": "block", "注册": "register", "数据组件": "data component",
    "数据生成": "data generation", "数据": "data", "组件": "component", "渲染": "render",
    "网络": "networking", "实体": "entity", "界面": "screen", "配方": "recipe",
    "战利品": "loot", "附魔": "enchantment", "维度": "dimension", "生物": "entity",
    "事件": "event", "资源": "resource", "模型": "model", "盔甲": "armor",
    "工具": "tool", "容器": "container", "流体": "fluid", "粒子": "particle",
    "命令": "command", "世界生成": "worldgen", "迁移": "migration", "版本": "version",
    "教程": "getting started", "音效": "sound", "菜单": "menu", "配置": "config",
    "标签": "tag", "进度": "advancement", "方块实体": "block entity",
}

SYNONYMS = {
    "gui": ["screen", "menu"],
    "registry": ["registration", "deferredregister"],
    "register": ["registration", "deferredregister"],
    "networking": ["payload", "packet"],
    "packet": ["payload"],
    "datagen": ["data generation", "datagenerator"],
    "datageneration": ["data generation"],
    "nbt": ["datacomponent", "compoundtag"],
    "model": ["models", "renderer"],
}


def connect(path: Path | None = None) -> sqlite3.Connection:
    db = Path(path) if path else config.db_path()
    con = sqlite3.connect("file:" + db.as_posix() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def version_key(version: str | None) -> str | None:
    if not version or version in ("current", "latest", ""):
        return "current"
    if version in ("all", "*"):
        return None
    labels = config.version_labels()
    for key, label in labels.items():
        if version == key or version == label:
            return key
    return version


def _detect_version(query: str) -> str | None:
    labels = config.version_labels()
    for m in VERSION_RE.finditer(query):
        candidate = m.group(1)
        for key, label in labels.items():
            if candidate == key or candidate == label:
                return key
    return None


def query_tokens(query: str) -> list[str]:
    text = CAMEL_RE.sub(r"\1 \2", query)
    raw = [t.lower() for t in TOKEN_RE.findall(text) if len(t) >= 2]
    primary = [t for t in raw if t not in STOP]
    if not primary:
        primary = raw
    out: list[str] = []
    for token in primary:
        if token not in out:
            out.append(token)
    for token in _zh_tokens(query):
        if token not in out:
            out.append(token)
    return out[:10]


def _zh_tokens(text: str) -> list[str]:
    out: list[str] = []
    for zh, en in ZH_TERMS.items():
        if zh in text:
            for part in en.split():
                if part not in out:
                    out.append(part)
    return out


def expand_tokens(tokens: list[str]) -> list[str]:
    out = list(tokens)
    for token in tokens:
        for extra in SYNONYMS.get(token, []):
            for part in extra.split():
                if part and part not in out:
                    out.append(part)
    return out[:14]


def build_match(tokens: list[str], mode: str, op: str = "OR") -> str:
    parts: list[str] = []
    for token in tokens:
        clean = token.replace('"', "").replace("*", "")
        if not clean:
            continue
        parts.append('"' + clean + '"*' if len(clean) >= 4 else '"' + clean + '"')
    if not parts:
        return ""
    expr = (" " + op + " ").join(parts)
    if mode == "api":
        return "symbols : (" + expr + ")"
    return expr


def make_snippet(text: str, tokens: list[str], width: int = SNIPPET_CHARS) -> str:
    low = text.lower()
    pos = -1
    for token in tokens:
        found = low.find(token)
        if found != -1 and (pos == -1 or found < pos):
            pos = found
    if pos == -1:
        pos = 0
    start = max(0, pos - 220)
    if start > 0:
        newline = text.find("\n", start)
        if newline != -1 and newline < pos:
            start = newline + 1
    end = min(len(text), start + width)
    if end < len(text):
        newline = text.rfind("\n", pos, end)
        if newline != -1 and newline > pos:
            end = newline
    snippet = text[start:end].strip()
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return prefix + snippet + suffix


def search(
    query: str,
    version: str = "current",
    section: str | None = None,
    limit: int = DEFAULT_LIMIT,
    mode: str = "text",
) -> dict[str, Any]:
    tokens = query_tokens(query)
    if not tokens:
        return {"query": query, "hits": [], "note": "empty query"}
    expanded = expand_tokens(tokens)

    note = None
    if version in ("current", "auto", ""):
        detected = _detect_version(query)
        if detected:
            version = detected
            note = "version auto-detected from query: " + detected
    vk = version_key(version)
    if vk and vk not in config.version_labels():
        note = "unknown version, falling back to current"
        vk = "current"

    match_and = build_match(tokens, mode, "AND")
    match_or = build_match(expanded, mode, "OR")
    match = match_and or match_or
    con = connect()
    try:
        rows = con.execute(
            """
            SELECT c.chunk_id AS chunk_id, c.doc_id AS doc_id, c.heading_path AS heading_path,
                   c.anchor AS anchor, c.text AS text, c.level AS level,
                   d.title AS title, d.url AS url, d.version AS version,
                   d.version_label AS version_label, d.section AS section,
                   d.slug AS slug, d.rel AS rel, d.group_label AS group_label,
                   -bm25(chunks_fts, 4.0, 2.5, 1.0, 2.0) AS score
            FROM chunks_fts
            JOIN chunks c ON c.rowid = chunks_fts.rowid
            JOIN docs d ON d.doc_id = c.doc_id
            WHERE chunks_fts MATCH ?
              AND (? IS NULL OR d.version = ?)
              AND (? IS NULL OR d.section = ?)
            ORDER BY score DESC
            LIMIT 150
            """,
            (match, vk, vk, section, section),
        ).fetchall()
        if len(rows) < 4 and match_or and match_or != match:
            rows = con.execute(
                "SELECT c.chunk_id AS chunk_id, c.doc_id AS doc_id,"
                " c.heading_path AS heading_path, c.anchor AS anchor, c.text AS text,"
                " c.level AS level, d.title AS title, d.url AS url, d.version AS version,"
                " d.version_label AS version_label, d.section AS section, d.slug AS slug,"
                " d.rel AS rel, d.group_label AS group_label,"
                " -bm25(chunks_fts, 4.0, 2.5, 1.0, 2.0) AS score"
                " FROM chunks_fts JOIN chunks c ON c.rowid = chunks_fts.rowid"
                " JOIN docs d ON d.doc_id = c.doc_id"
                " WHERE chunks_fts MATCH ?"
                "   AND (? IS NULL OR d.version = ?)"
                "   AND (? IS NULL OR d.section = ?)"
                " ORDER BY score DESC LIMIT 150",
                (match_or, vk, vk, section, section),
            ).fetchall()
    finally:
        con.close()

    candidates: list[dict[str, Any]] = []
    for row in rows:
        weight = 1.0 if row["version"] == "current" else 0.8
        score = float(row["score"]) * weight
        title_lc = row["title"].lower()
        heading_lc = row["heading_path"].lower()
        heading_only = heading_lc[len(title_lc) + 3:] if heading_lc.startswith(title_lc + " > ") else heading_lc
        bonus = 1.0
        for token in tokens:
            if len(token) < 3:
                continue
            if title_lc.startswith(token) or any(word.startswith(token) for word in title_lc.split()):
                bonus = max(bonus, 1.4)
            elif any(word.startswith(token) for word in heading_only.split()):
                bonus = max(bonus, 1.15)
        score *= bonus
        path = row["rel"][:-3] if row["rel"].endswith(".md") else row["rel"]
        candidates.append(
            {
                "doc_id": row["doc_id"],
                "path": path,
                "title": row["title"],
                "heading": row["heading_path"],
                "anchor": row["anchor"],
                "version": row["version_label"],
                "section": row["section"],
                "url": row["url"] + ("#" + row["anchor"] if row["anchor"] else ""),
                "score": round(score, 2),
                "group": row["group_label"],
                "snippet": make_snippet(row["text"], expanded),
                "_doc_key": row["section"] + "|" + row["slug"],
            }
        )
    candidates.sort(key=lambda item: item["score"], reverse=True)

    hits: list[dict[str, Any]] = []
    per_doc: dict[str, int] = {}
    per_heading: set[str] = set()
    for item in candidates:
        doc_key = item.pop("_doc_key")
        heading_key = doc_key + "|" + item["heading"]
        if heading_key in per_heading or per_doc.get(doc_key, 0) >= 2:
            continue
        per_heading.add(heading_key)
        per_doc[doc_key] = per_doc.get(doc_key, 0) + 1
        hits.append(item)
        if len(hits) >= max(1, min(limit, MAX_LIMIT)):
            break

    result: dict[str, Any] = {"query": query, "version": (vk or "all"), "hits": hits}
    if hits:
        first = hits[0]
        result["next"] = 'get_section(doc_id="' + first["doc_id"] + '", heading="' + first["anchor"] + '")'
    if note:
        result["note"] = note
    return result


def resolve_doc(con: sqlite3.Connection, ref: str, version: str = "current") -> sqlite3.Row | None:
    ref = (ref or "").strip()
    if not ref:
        return None
    if ":" in ref:
        row = con.execute("SELECT * FROM docs WHERE doc_id = ?", (ref,)).fetchone()
        if row is not None:
            return row
    vk = version_key(version) or "current"
    clean = ref.split("#")[0].strip().lstrip("/").rstrip("/")
    clean = re.sub(r"\.mdx?$", "", clean)
    for section in ("docs", "toolchain", "user", "modpack"):
        local = clean
        for prefix in ("docs/", section + "/"):
            if local.startswith(prefix):
                local = local[len(prefix):]
                break
        local = re.sub(r"^(docs|" + section + r")/", "", local)
        for rel in (local + ".md", local + "/index.md", local):
            row = con.execute(
                "SELECT * FROM docs WHERE section = ? AND version = ? AND rel = ?",
                (section, vk, rel),
            ).fetchone()
            if row is not None:
                return row
    if clean:
        return con.execute(
            "SELECT * FROM docs WHERE version = ? AND slug = ? LIMIT 1", (vk, clean)
        ).fetchone()
    return None


def _doc_text(con: sqlite3.Connection, doc_id: str) -> tuple[str, list[dict[str, Any]]]:
    chunks = con.execute(
        "SELECT anchor, heading_path, text FROM chunks WHERE doc_id = ? ORDER BY ord", (doc_id,)
    ).fetchall()
    parts = [c["text"] for c in chunks]
    headings = [{"anchor": c["anchor"], "heading": c["heading_path"]} for c in chunks if c["anchor"]]
    return "\n\n".join(parts), headings


def get_doc(doc_id: str, version: str = "current") -> dict[str, Any]:
    con = connect()
    try:
        row = resolve_doc(con, doc_id, version)
        if row is None:
            return {"error": "document not found", "doc_id": doc_id, "version": version}
        text, headings = _doc_text(con, row["doc_id"])
        return {
            "doc_id": row["doc_id"],
            "title": row["title"],
            "version": row["version_label"],
            "section": row["section"],
            "url": row["url"],
            "group": row["group_label"],
            "headings": headings,
            "text": "# " + row["title"] + "\n\n" + text,
        }
    finally:
        con.close()


def get_section(doc_id: str, heading: str, version: str = "current") -> dict[str, Any]:
    con = connect()
    try:
        row = resolve_doc(con, doc_id, version)
        if row is None:
            return {"error": "document not found", "doc_id": doc_id, "version": version}
        target = slugify(heading)
        chunks = con.execute(
            "SELECT anchor, heading_path, text FROM chunks WHERE doc_id = ? ORDER BY ord",
            (row["doc_id"],),
        ).fetchall()
        match = None
        for chunk in chunks:
            if target and chunk["anchor"] == target:
                match = chunk
                break
        if match is None:
            needle = heading.strip().lower()
            for chunk in chunks:
                if needle and needle in chunk["heading_path"].lower():
                    match = chunk
                    break
        if match is None:
            return {
                "error": "section not found",
                "doc_id": row["doc_id"],
                "available": [c["anchor"] for c in chunks if c["anchor"]][:40],
            }
        return {
            "doc_id": row["doc_id"],
            "title": row["title"],
            "version": row["version_label"],
            "url": row["url"] + ("#" + match["anchor"] if match["anchor"] else ""),
            "heading": match["heading_path"],
            "anchor": match["anchor"],
            "text": match["text"],
        }
    finally:
        con.close()


def list_docs(version: str = "current", section: str | None = None) -> dict[str, Any]:
    vk = version_key(version) or "current"
    con = connect()
    try:
        rows = con.execute(
            "SELECT section, rel, slug, title, url, group_label, n_tokens FROM docs"
            " WHERE version = ? AND (? IS NULL OR section = ?) ORDER BY section, rel",
            (vk, section, section),
        ).fetchall()
    finally:
        con.close()
    pages: list[dict[str, Any]] = []
    for row in rows:
        path = row["rel"][:-3] if row["rel"].endswith(".md") else row["rel"]
        pages.append(
            {
                "path": path,
                "title": row["title"],
                "section": row["section"],
                "group": row["group_label"],
                "url": row["url"],
            }
        )
    return {"version": vk, "count": len(pages), "pages": pages}


def find_symbol(symbol: str, limit: int = 10) -> dict[str, Any]:
    needle = (symbol or "").strip()
    if not needle:
        return {"symbol": symbol, "hits": [], "note": "empty symbol"}
    con = connect()
    try:
        rows = con.execute(
            """
            SELECT s.sym AS sym, s.doc_id AS doc_id, s.chunk_id AS chunk_id,
                   d.title AS title, d.version AS version, d.version_label AS version_label,
                   d.url AS url, d.rel AS rel, c.heading_path AS heading_path, c.anchor AS anchor,
                   c.text AS text
            FROM symbols s
            JOIN docs d ON d.doc_id = s.doc_id
            JOIN chunks c ON c.chunk_id = s.chunk_id
            WHERE s.sym_lc = ?
            ORDER BY CASE WHEN d.version = 'current' THEN 0 ELSE 1 END,
                     CASE WHEN c.heading_path LIKE '%' || ? || '%' THEN 0 ELSE 1 END,
                     length(s.sym), d.title
            LIMIT 60
            """,
            (needle.lower(), needle),
        ).fetchall()
        if not rows:
            rows = con.execute(
                """
                SELECT s.sym AS sym, s.doc_id AS doc_id, s.chunk_id AS chunk_id,
                       d.title AS title, d.version AS version, d.version_label AS version_label,
                       d.url AS url, d.rel AS rel, c.heading_path AS heading_path, c.anchor AS anchor,
                       c.text AS text
                FROM symbols s
                JOIN docs d ON d.doc_id = s.doc_id
                JOIN chunks c ON c.chunk_id = s.chunk_id
                WHERE s.sym_lc LIKE ?
                ORDER BY CASE WHEN d.version = 'current' THEN 0 ELSE 1 END,
                         CASE WHEN c.heading_path LIKE '%' || ? || '%' THEN 0 ELSE 1 END,
                         length(s.sym), d.title
                LIMIT 60
                """,
                ("%" + needle.lower() + "%", needle),
            ).fetchall()
    finally:
        con.close()

    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = row["doc_id"] + "#" + row["anchor"]
        if key in seen:
            continue
        seen.add(key)
        text = row["text"]
        pos = text.lower().find(row["sym"].lower())
        context = text[max(0, pos - 120): pos + 220].replace("\n", " ").strip() if pos != -1 else ""
        path = row["rel"][:-3] if row["rel"].endswith(".md") else row["rel"]
        hits.append(
            {
                "symbol": row["sym"],
                "doc_id": row["doc_id"],
                "path": path,
                "title": row["title"],
                "heading": row["heading_path"],
                "version": row["version_label"],
                "url": row["url"] + ("#" + row["anchor"] if row["anchor"] else ""),
                "context": context[:260],
            }
        )
        if len(hits) >= max(1, min(limit, 20)):
            break
    return {"symbol": needle, "count": len(hits), "hits": hits}


def compare_versions(rel_or_doc: str, from_version: str = "1.21.1", to_version: str = "current") -> dict[str, Any]:
    con = connect()
    try:
        src = resolve_doc(con, rel_or_doc, from_version)
        if src is None:
            return {"error": "document not found in " + from_version, "doc": rel_or_doc}
        dst = con.execute(
            "SELECT * FROM docs WHERE section = ? AND version = ? AND rel = ?",
            (src["section"], version_key(to_version) or "current", src["rel"]),
        ).fetchone()
        if dst is None:
            return {
                "error": "no matching document in " + to_version,
                "doc": src["rel"],
                "hint": "use search_docs(version=\"all\") to check whether the page exists in that version",
            }
        old_text, _ = _doc_text(con, src["doc_id"])
        new_text, _ = _doc_text(con, dst["doc_id"])
    finally:
        con.close()

    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    diff = list(
        difflib.unified_diff(
            old_lines, new_lines,
            fromfile=src["version_label"] + "/" + src["rel"],
            tofile=dst["version_label"] + "/" + dst["rel"],
            n=2,
            lineterm="",
        )
    )
    added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
    body = "\n".join(diff[:240])
    return {
        "doc": src["rel"],
        "from": src["version_label"],
        "to": dst["version_label"],
        "added_lines": added,
        "removed_lines": removed,
        "truncated": len(diff) > 240,
        "diff": body,
    }


def ensure_index() -> dict[str, Any]:
    from . import index as indexer

    return indexer.ensure_index()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="neoforge-docs-search", description="Query the local docs index.")
    parser.add_argument("query")
    parser.add_argument("--version", default="current")
    parser.add_argument("--section", default=None)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--mode", default="text", choices=["text", "api"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = search(args.query, version=args.version, section=args.section, limit=args.limit, mode=args.mode)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("version:", result.get("version"), "hits:", len(result.get("hits", [])))
        for hit in result.get("hits", []):
            print("-", hit["score"], hit["title"], "|", hit["heading"])
            print("  ", hit["url"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
