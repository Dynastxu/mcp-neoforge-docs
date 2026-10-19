"""Generate an MCP client config with paths resolved on this machine.

Nothing machine-specific belongs in the repository: the interpreter path is taken
from the running Python (sys.executable), and the docs root from the resolution
rules in config.py, so the same command works after moving or cloning the repo.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config


def build(client: str = "generic", docs_root: Path | None = None) -> dict:
    root = docs_root or config.docs_root()
    entry = {
        "command": sys.executable,
        "args": ["-m", "neoforge_docs_mcp"],
        "env": {"NEOFORGE_DOCS_ROOT": str(root)},
    }
    if client == "vscode":
        return {"servers": {"neoforge-docs": {"type": "stdio", **entry}}}
    return {"mcpServers": {"neoforge-docs": entry}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="neoforge-docs-config",
        description="Emit (or write) an MCP client config for this checkout.",
    )
    parser.add_argument("--client", choices=["generic", "vscode"], default="generic",
                        help="generic = mcpServers (most clients); vscode = servers")
    parser.add_argument("--output", default=None, help="write to this path instead of stdout")
    parser.add_argument("--docs-root", default=None, help="override the documentation checkout")
    parser.add_argument("--force", action="store_true", help="overwrite an existing output file")
    args = parser.parse_args(argv)

    if sys.prefix == sys.base_prefix:
        print("warning: not running inside a virtualenv; the emitted command may lack the mcp package",
              file=sys.stderr)

    payload = build(args.client, Path(args.docs_root).expanduser().resolve() if args.docs_root else None)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    if not args.output:
        print(text, end="")
        return 0

    target = Path(args.output)
    if target.exists() and not args.force:
        print("refusing to overwrite " + str(target) + " (pass --force)", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print("wrote " + str(target), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
