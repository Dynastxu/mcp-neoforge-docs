"""Paths and corpus-level configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PKG_ROOT.parent.parent
BASE_URL = "https://docs.neoforged.net"

# (section, sub-directory of the docs checkout, route prefix)
SECTIONS: list[tuple[str, str, str]] = [
    ("docs", "docs", "/docs"),
    ("toolchain", "toolchain/docs", "/toolchain/docs"),
    ("user", "user/docs", "/user/docs"),
    ("modpack", "modpack/docs", "/modpack/docs"),
]


def docs_root() -> Path:
    env = os.environ.get("NEOFORGE_DOCS_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return (REPO_ROOT / "neoforge-docs").resolve()


def db_path() -> Path:
    env = os.environ.get("NEOFORGE_DOCS_DB")
    if env:
        return Path(env).expanduser().resolve()
    return (REPO_ROOT / "data" / "neoforge-docs.sqlite3").resolve()


def version_labels(root: Path | None = None) -> dict[str, str]:
    """Map a version key ("current", "1.21.1", ...) to its display label."""
    base = root or docs_root()
    try:
        raw = json.loads((base / "version_labels.json").read_text(encoding="utf-8"))
    except Exception:
        return {"current": "current"}
    labels: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            labels[key] = str(value.get("label", key))
        else:
            labels[key] = str(value)
    labels.setdefault("current", "current")
    return labels
