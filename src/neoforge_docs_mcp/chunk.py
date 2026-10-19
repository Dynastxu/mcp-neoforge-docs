"""Heading-aware chunking for the documentation corpus."""

from __future__ import annotations

from dataclasses import dataclass

from .parse import FENCE_RE, HEADING_RE, slugify, split_fences

MAX_TOKENS = 1100
MIN_TOKENS = 110
SOFT_SPLIT = 320


@dataclass
class Chunk:
    heading_path: str
    anchor: str
    level: int
    text: str
    n_tokens: int


def approx_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _blocks(body: str) -> list[tuple[str, int, str]]:
    blocks: list[tuple[str, int, str]] = []
    for is_code, seg in split_fences(body):
        if is_code:
            blocks.append(("code", 0, seg.strip("\n")))
            continue
        buf: list[str] = []
        for line in seg.split("\n"):
            m = HEADING_RE.match(line)
            if m:
                if buf:
                    blocks.append(("text", 0, "\n".join(buf).strip()))
                    buf = []
                blocks.append(("heading", len(m.group(1)), m.group(2).strip()))
                continue
            if not line.strip():
                if buf:
                    blocks.append(("text", 0, "\n".join(buf).strip()))
                    buf = []
                continue
            buf.append(line)
        if buf:
            blocks.append(("text", 0, "\n".join(buf).strip()))
    return [b for b in blocks if b[2].strip()]


def _pack(blocks: list[str], max_tokens: int = MAX_TOKENS) -> list[str]:
    pieces: list[str] = []
    cur: list[str] = []
    cur_tok = 0
    for b in blocks:
        t = approx_tokens(b)
        if cur and cur_tok + t > max_tokens:
            pieces.append("\n\n".join(cur))
            cur = []
            cur_tok = 0
        cur.append(b)
        cur_tok += t
    if cur:
        pieces.append("\n\n".join(cur))
    return pieces


def _split_large(text: str, max_tokens: int = MAX_TOKENS) -> list[str]:
    """Split an oversized block at line boundaries, never inside a code fence."""
    lines = text.split("\n")
    pieces: list[str] = []
    cur: list[str] = []
    cur_tok = 0
    in_fence = False
    for line in lines:
        if FENCE_RE.match(line):
            in_fence = not in_fence
        t = approx_tokens(line) if line else 1
        if not in_fence and cur and cur_tok + t > max_tokens:
            pieces.append("\n".join(cur).strip("\n"))
            cur = []
            cur_tok = 0
        cur.append(line)
        cur_tok += t
    if cur:
        pieces.append("\n".join(cur).strip("\n"))
    return [p for p in pieces if p.strip()]


def build_chunks(title: str, body: str) -> list[Chunk]:
    blocks = _blocks(body)
    chunks: list[Chunk] = []
    used: dict[str, int] = {}

    def _uniq(text: str) -> str:
        base = slugify(text) or "section"
        n = used.get(base, 0)
        used[base] = n + 1
        return base if n == 0 else base + "-" + str(n)

    stack: list[str] = []
    buf: list[str] = []
    section_anchor = ""

    def flush() -> None:
        nonlocal buf
        if not buf:
            return
        current = buf
        buf = []
        total = sum(approx_tokens(b) for b in current)
        parts = ["\n\n".join(current)] if total <= MAX_TOKENS else _pack(current)
        expanded: list[str] = []
        for part in parts:
            if approx_tokens(part) > MAX_TOKENS * 3 // 2:
                expanded.extend(_split_large(part))
            else:
                expanded.append(part)
        for part in expanded:
            part = part.strip()
            if not part:
                continue
            if stack:
                heading_path = " > ".join([title] + stack)
                anchor = section_anchor
                level = len(stack) + 1
            else:
                heading_path = title
                anchor = ""
                level = 1
            chunks.append(Chunk(heading_path, anchor, level, part, approx_tokens(part)))

    for kind, level, text in blocks:
        if kind == "heading":
            if level == 1:
                if text.strip().lower() != title.strip().lower():
                    buf.append(text)
                continue
            if level == 2:
                flush()
                stack = [text]
                section_anchor = _uniq(text)
                buf = ["## " + text]
                continue
            if level == 3:
                if sum(approx_tokens(b) for b in buf) > SOFT_SPLIT:
                    flush()
                    stack = stack[:1] + [text]
                    section_anchor = _uniq(text)
                    buf = ["### " + text]
                else:
                    buf.append("### " + text)
                continue
            buf.append("#" * level + " " + text)
            continue
        buf.append(text)
    flush()

    merged: list[Chunk] = []
    for c in chunks:
        if (
            merged
            and c.n_tokens < MIN_TOKENS
            and merged[-1].heading_path == c.heading_path
            and merged[-1].n_tokens + c.n_tokens <= MAX_TOKENS
        ):
            prev = merged[-1]
            prev.text = prev.text + "\n\n" + c.text
            prev.n_tokens = approx_tokens(prev.text)
        else:
            merged.append(c)
    return merged
