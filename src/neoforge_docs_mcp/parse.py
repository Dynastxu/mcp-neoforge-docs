"""Markdown parsing and cleaning for the bundled NeoForge documentation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

BT = chr(96)

FENCE_RE = re.compile(r"^\s*(" + BT + r"{3,}|~{3,})(.*)$")
FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*\r?\n", re.S)
IMPORT_RE = re.compile(r"^\s*import\s+.+?\s+from\s+['\"][^'\"]+['\"];[ \t]*$", re.M)
REF_DEF_RE = re.compile(r"^\[([^\]\n]+)\]:[ \t]*(\S+)(?:[ \t]+[\"'(].*)?$", re.M)
REF_LINK_RE = re.compile(r"(?<!!)\[([^\]\n]+)\]\[([^\]\n]*)\]")
INLINE_LINK_RE = re.compile(r"(?<!!)\[([^\]\n]+)\]\(([^()\s]+)(?:[ \t]+[\"'][^\"']*[\"'])?\)")
IMAGE_RE = re.compile(r"!\[([^\]\n]*)\]\([^)\n]*\)")
SHORTCUT_REF_RE = re.compile(r"(?<!!)\[([^\]\n]+)\](?![\[(])")
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
JSX_TAG_RE = re.compile(
    r"</?(?:Tabs|TabItem|CodeBlock|Admonition|details|summary|div|span|p|br|img|Badge|DocCardList)\b[^>]*>",
    re.I,
)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
MULTI_BLANK_RE = re.compile(r"\n{3,}")
INLINE_CODE_RE = re.compile(BT + r"([^" + BT + r"\n]+)" + BT)


@dataclass
class ParsedDoc:
    rel: str
    title: str
    body: str
    intro: str
    frontmatter: dict = field(default_factory=dict)
    refs: dict[str, str] = field(default_factory=dict)
    links: list[tuple[str, str]] = field(default_factory=list)


def split_fences(text: str) -> list[tuple[bool, str]]:
    """Split markdown into (is_code, segment) pairs; fenced blocks stay whole."""
    out: list[tuple[bool, str]] = []
    buf: list[str] = []
    fence: str | None = None
    for line in text.split("\n"):
        if fence is not None:
            buf.append(line)
            m = FENCE_RE.match(line)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not m.group(2).strip():
                out.append((True, "\n".join(buf)))
                buf = []
                fence = None
            continue
        m = FENCE_RE.match(line)
        if m:
            if buf:
                out.append((False, "\n".join(buf)))
                buf = []
            fence = m.group(1)
            buf = [line]
            continue
        buf.append(line)
    if buf:
        out.append((fence is not None, "\n".join(buf)))
    return out


def strip_frontmatter(text: str) -> tuple[dict, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except Exception:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, text[m.end():]


def _collect_refs(text: str) -> tuple[str, dict[str, str]]:
    refs: dict[str, str] = {}
    kept: list[str] = []
    for line in text.split("\n"):
        m = REF_DEF_RE.match(line.strip())
        if m:
            refs[m.group(1).strip().lower()] = m.group(2).strip()
            continue
        kept.append(line)
    return "\n".join(kept), refs


def _clean_text(text: str, refs: dict[str, str], links: list[tuple[str, str]]) -> str:
    text = HTML_COMMENT_RE.sub("", text)
    text = JSX_TAG_RE.sub("", text)

    def _img(m: re.Match[str]) -> str:
        return m.group(1).strip() or ""

    text = IMAGE_RE.sub(_img, text)

    def _ref(m: re.Match[str]) -> str:
        label = m.group(1)
        ref = (m.group(2) or label).strip().lower()
        target = refs.get(ref, "")
        if target:
            links.append((label, target))
        return label

    text = REF_LINK_RE.sub(_ref, text)
    text = INLINE_LINK_RE.sub(lambda m: m.group(1), text)

    def _shortcut(m: re.Match[str]) -> str:
        label = m.group(1)
        return label if label.strip().lower() in refs else m.group(0)

    text = SHORTCUT_REF_RE.sub(_shortcut, text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return text


def plain(text: str) -> str:
    text = INLINE_CODE_RE.sub(r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"[*_]{1,2}(.+?)[*_]{1,2}", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return text.strip()


def slugify(text: str) -> str:
    s = plain(text).lower()
    s = re.sub(r"[^\w\- ]+", "", s)
    s = re.sub(r"\s+", "-", s.strip())
    return s.strip("-")


def title_from_rel(rel: str) -> str:
    stem = rel[:-3] if rel.endswith(".md") else rel
    parts = [p for p in stem.split("/") if p]
    if not parts:
        return "Documentation"
    name = parts[-1]
    if name == "index" and len(parts) > 1:
        name = parts[-2]
    return name.replace("-", " ").replace("_", " ").title()


def _first_h1(body: str) -> str | None:
    in_fence = False
    for line in body.split("\n"):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = HEADING_RE.match(line)
        if m and len(m.group(1)) == 1:
            return plain(m.group(2))
    return None


def _drop_h1(body: str) -> str:
    in_fence = False
    out: list[str] = []
    dropped = False
    for line in body.split("\n"):
        if FENCE_RE.match(line):
            in_fence = not in_fence
        if not dropped and not in_fence:
            m = HEADING_RE.match(line)
            if m and len(m.group(1)) == 1:
                dropped = True
                continue
        out.append(line)
    return "\n".join(out)


def _intro(body: str, limit: int = 300) -> str:
    para: list[str] = []
    in_fence = False
    for line in body.split("\n"):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if HEADING_RE.match(line):
            if para:
                break
            continue
        if not line.strip():
            if para:
                break
            continue
        para.append(line.strip())
    return " ".join(para)[:limit].strip()


def parse_doc(path: Path, rel: str) -> ParsedDoc:
    raw = path.read_text(encoding="utf-8", errors="replace")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    meta, raw = strip_frontmatter(raw)
    raw = IMPORT_RE.sub("", raw)

    segments = split_fences(raw)
    refs: dict[str, str] = {}
    for is_code, seg in segments:
        if not is_code:
            _, seg_refs = _collect_refs(seg)
            refs.update(seg_refs)

    links: list[tuple[str, str]] = []
    cleaned: list[str] = []
    for is_code, seg in segments:
        if is_code:
            cleaned.append(seg)
        else:
            stripped, _ = _collect_refs(seg)
            cleaned.append(_clean_text(stripped, refs, links))

    body = MULTI_BLANK_RE.sub("\n\n", "\n".join(cleaned)).strip() + "\n"
    title = _first_h1(body) or str(meta.get("sidebar_label") or "").strip() or title_from_rel(rel)
    body = _drop_h1(body).strip() + "\n"
    return ParsedDoc(
        rel=rel,
        title=title,
        body=body,
        intro=_intro(body),
        frontmatter=meta,
        refs=refs,
        links=links,
    )
