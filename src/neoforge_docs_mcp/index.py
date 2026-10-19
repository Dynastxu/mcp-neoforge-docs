"""Build the local SQLite + FTS5 index over the NeoForge docs checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import posixpath
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .chunk import build_chunks
from .parse import BT as BACKTICK, parse_doc

log = logging.getLogger("neoforge_docs.index")

SCHEMA = """
CREATE TABLE docs(
  doc_id TEXT PRIMARY KEY,
  section TEXT NOT NULL,
  version TEXT NOT NULL,
  version_label TEXT NOT NULL,
  rel TEXT NOT NULL,
  slug TEXT NOT NULL,
  title TEXT NOT NULL,
  group_label TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL,
  intro TEXT NOT NULL DEFAULT '',
  n_tokens INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX idx_docs_identity ON docs(section, version, rel);
CREATE INDEX idx_docs_version ON docs(version, section);
CREATE TABLE chunks(
  chunk_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  ord INTEGER NOT NULL,
  heading_path TEXT NOT NULL,
  anchor TEXT NOT NULL,
  level INTEGER NOT NULL,
  text TEXT NOT NULL,
  n_tokens INTEGER NOT NULL
);
CREATE INDEX idx_chunks_doc ON chunks(doc_id, ord);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
  title, heading, body, symbols, tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE symbols(
  sym TEXT NOT NULL,
  sym_lc TEXT NOT NULL,
  doc_id TEXT NOT NULL,
  chunk_id TEXT NOT NULL
);
CREATE INDEX idx_symbols_lc ON symbols(sym_lc);
CREATE TABLE links(
  src_doc TEXT NOT NULL,
  dst_rel TEXT NOT NULL,
  anchor TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_links_src ON links(src_doc);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

CODE_SPAN_RE = re.compile(BACKTICK + r"([^" + BACKTICK + r"\n]{2,120})" + BACKTICK)
JAVA_SYM_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*(?:\.[a-z][A-Za-z0-9_]*)*(?:#[a-zA-Z_][A-Za-z0-9_]*)?)\b")
CAMEL_SPLIT_RE = re.compile(r"([a-z0-9])([A-Z])")
STOP_SYMBOLS = {
    "This", "The", "That", "These", "Those", "Then", "There", "They", "When", "Where",
    "Which", "While", "With", "What", "Note", "However", "Because", "Also", "Some",
    "All", "Any", "Each", "Every", "For", "And", "But", "Not", "You", "Your", "Use",
    "See", "If", "It", "In", "On", "To", "Of", "Or", "As", "At", "By", "Is", "Be",
    "Minecraft", "Java", "JSON", "HTML", "API", "TODO", "URL", "ID", "IO", "NBT",
}


@dataclass
class Source:
    path: Path
    base: Path
    section: str
    version: str
    version_label: str
    rel: str
    prefix: str


def extract_symbols(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = value.strip()
        if not (2 <= len(value) <= 90):
            return
        if value in seen:
            return
        seen.add(value)
        found.append(value)

    for m in CODE_SPAN_RE.finditer(text):
        span = m.group(1).strip()
        if not span or " " in span:
            continue
        if span.startswith(("http", "//", "#")):
            continue
        add(span)

    for m in JAVA_SYM_RE.finditer(text):
        sym = m.group(1)
        if sym in STOP_SYMBOLS or len(sym) < 4:
            continue
        if not ("." in sym or "#" in sym or any(c.isupper() for c in sym[1:])):
            continue
        add(sym)
    return found[:80]


def flatten_symbol(sym: str) -> str:
    flat = CAMEL_SPLIT_RE.sub(r"\1 \2", sym)
    return re.sub(r"[.#_/]+", " ", flat)


def fingerprint(root: Path) -> str:
    h = hashlib.sha256()
    files = sorted(root.rglob("*.md"))
    for path in files:
        try:
            st = path.stat()
        except OSError:
            continue
        h.update(path.relative_to(root).as_posix().encode("utf-8"))
        h.update(b":")
        h.update(str(st.st_size).encode("ascii"))
        h.update(b":")
        h.update(str(st.st_mtime_ns).encode("ascii"))
        h.update(b"\n")
    labels = root / "version_labels.json"
    if labels.is_file():
        h.update(labels.read_bytes())
    return h.hexdigest()[:32]


def iter_sources(root: Path):
    labels = config.version_labels(root)
    for section, sub, prefix in config.SECTIONS:
        base = root / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            yield Source(path, base, section, "current", labels.get("current", "current"),
                         path.relative_to(base).as_posix(), prefix)
    versioned = root / "versioned_docs"
    if versioned.is_dir():
        for directory in sorted(p for p in versioned.iterdir() if p.is_dir() and p.name.startswith("version-")):
            version = directory.name[len("version-"):]
            for path in sorted(directory.rglob("*.md")):
                yield Source(path, directory, "docs", version, labels.get(version, version),
                             path.relative_to(directory).as_posix(), "/docs/" + version)


def group_for(base: Path, rel: str) -> str:
    labels: list[str] = []
    current = base
    for part in rel.split("/")[:-1]:
        current = current / part
        category = current / "_category_.json"
        if not category.is_file():
            continue
        try:
            data = json.loads(category.read_text(encoding="utf-8"))
        except Exception:
            continue
        label = data.get("label")
        if label:
            labels.append(str(label))
    return " / ".join(labels)


def slug_and_url(rel: str, prefix: str) -> tuple[str, str]:
    stem = rel[:-3] if rel.endswith(".md") else rel
    is_index = stem == "index" or stem.endswith("/index")
    if stem == "index":
        slug = ""
    elif is_index:
        slug = stem[: -len("/index")]
    else:
        slug = stem
    if slug:
        url = config.BASE_URL + prefix + "/" + slug + ("/" if is_index else "")
    else:
        url = config.BASE_URL + prefix + "/"
    return slug, url


def link_target(rel: str, target: str) -> tuple[str, str] | None:
    target = target.strip()
    if not target or target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    path, _, anchor = target.partition("#")
    if not path or path.startswith("/"):
        return None
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(rel), path))
    if joined.startswith("..") or not (joined.endswith(".md") or joined.endswith(".mdx")):
        return None
    return joined, anchor


def build(db_path: Path | None = None, force: bool = False) -> dict:
    root = config.docs_root()
    if not (root / "docs").is_dir():
        raise RuntimeError(
            "documentation checkout not found at " + str(root) + " (run: git submodule update --init)"
        )
    db = Path(db_path) if db_path else config.db_path()
    db.parent.mkdir(parents=True, exist_ok=True)

    fp = fingerprint(root)
    if db.exists() and not force:
        try:
            con = sqlite3.connect(db)
            row = con.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone()
            con.close()
            if row and row[0] == fp:
                return {"status": "up_to_date", "db": str(db), "fingerprint": fp}
        except sqlite3.Error:
            pass

    started = time.perf_counter()
    tmp = db.with_name(db.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)

    docs = 0
    chunk_count = 0
    symbol_count = 0
    seen_chunk_ids: set[str] = set()

    for src in iter_sources(root):
        try:
            parsed = parse_doc(src.path, src.rel)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("skip %s: %s", src.rel, exc)
            continue
        chunks = build_chunks(parsed.title, parsed.body)
        if not chunks:
            continue
        doc_id = src.section + ":" + src.version + ":" + src.rel
        slug, url = slug_and_url(src.rel, src.prefix)
        total_tokens = sum(c.n_tokens for c in chunks)
        con.execute(
            "INSERT INTO docs(doc_id, section, version, version_label, rel, slug, title,"
            " group_label, url, intro, n_tokens) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (doc_id, src.section, src.version, src.version_label, src.rel, slug,
             parsed.title, group_for(src.base, src.rel), url, parsed.intro, total_tokens),
        )
        for i, ch in enumerate(chunks):
            chunk_id = doc_id + "#" + str(i)
            if chunk_id in seen_chunk_ids:
                chunk_id = chunk_id + "x"
            seen_chunk_ids.add(chunk_id)
            cur = con.execute(
                "INSERT INTO chunks(chunk_id, doc_id, ord, heading_path, anchor, level, text, n_tokens)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (chunk_id, doc_id, i, ch.heading_path, ch.anchor, ch.level, ch.text, ch.n_tokens),
            )
            syms = extract_symbols(ch.text)
            con.execute(
                "INSERT INTO chunks_fts(rowid, title, heading, body, symbols) VALUES(?,?,?,?,?)",
                (cur.lastrowid, parsed.title, ch.heading_path, ch.text,
                 " ".join(flatten_symbol(s) for s in syms)),
            )
            for sym in syms:
                con.execute(
                    "INSERT INTO symbols(sym, sym_lc, doc_id, chunk_id) VALUES(?,?,?,?)",
                    (sym, sym.lower(), doc_id, chunk_id),
                )
                symbol_count += 1
            chunk_count += 1
        for _label, target in parsed.links:
            resolved = link_target(src.rel, target)
            if resolved is None:
                continue
            dst_rel, anchor = resolved
            con.execute("INSERT INTO links(src_doc, dst_rel, anchor) VALUES(?,?,?)", (doc_id, dst_rel, anchor))
        docs += 1

    built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con.executemany(
        "INSERT INTO meta(key, value) VALUES(?,?)",
        [
            ("fingerprint", fp),
            ("built_at", built_at),
            ("docs_root", str(root)),
            ("docs", str(docs)),
            ("chunks", str(chunk_count)),
            ("symbols", str(symbol_count)),
            ("labels", json.dumps(config.version_labels(root), ensure_ascii=False)),
        ],
    )
    con.commit()
    con.close()

    if db.exists():
        db.unlink()
    tmp.replace(db)
    elapsed = round(time.perf_counter() - started, 2)
    result = {
        "status": "built",
        "db": str(db),
        "docs": docs,
        "chunks": chunk_count,
        "symbols": symbol_count,
        "seconds": elapsed,
        "fingerprint": fp,
    }
    log.info("indexed %s docs / %s chunks in %ss", docs, chunk_count, elapsed)
    return result


def ensure_index(force: bool = False) -> dict:
    return build(config.db_path(), force=force)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="neoforge-docs-index",
        description="Build (or refresh) the local NeoForge documentation index.",
    )
    parser.add_argument("--db", default=None, help="override the SQLite output path")
    parser.add_argument("--force", action="store_true", help="rebuild even when the corpus is unchanged")
    args = parser.parse_args(argv)
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[neoforge-docs-index] %(message)s")
    result = build(Path(args.db) if args.db else None, force=args.force)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
