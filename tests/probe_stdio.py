"""Raw JSON-RPC probe over real stdio pipes (sync subprocess, thread reader)."""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def resolve_launch(config_path: Path | None) -> tuple[list[str], dict[str, str] | None, str]:
    """Use an explicit client config when given, else this interpreter."""
    if config_path and config_path.is_file():
        data = json.loads(config_path.read_text(encoding="utf-8"))
        entry = (data.get("mcpServers") or data.get("servers") or {}).get("neoforge-docs")
        if entry:
            command = [entry["command"], *entry.get("args", [])]
            env = {**os.environ, **entry.get("env", {})}
            return command, env, str(config_path)
    return [sys.executable, "-m", "neoforge_docs_mcp"], None, "module"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Raw JSON-RPC probe over stdio pipes.")
    parser.add_argument("--config", default=None, help="MCP client config JSON to launch from")
    args = parser.parse_args(argv)
    command, env, source = resolve_launch(Path(args.config) if args.config else None)
    print("launcher:", source, "|", command[0])
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
        cwd=str(ROOT),
        env=env,
    )
    lines: "queue.Queue[str]" = queue.Queue()

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line)
        lines.put("")

    threading.Thread(target=pump, daemon=True).start()

    def send(payload: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()

    def recv(timeout: float = 20.0) -> dict | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if not line:
                return None
            return json.loads(line)
        return None

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                     "clientInfo": {"name": "probe", "version": "0"}}})
    init = recv()
    print("initialize ->", "ok" if init and "result" in init else init)

    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    listing = recv()
    names = [t["name"] for t in listing["result"]["tools"]] if listing else []
    print("tools/list ->", names)

    send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
          "params": {"name": "search_docs", "arguments": {"query": "custom armor", "limit": 1}}})
    call = recv()
    if call and "result" in call:
        payload = json.loads(call["result"]["content"][0]["text"])
        hit = payload["hits"][0]
        print("tools/call ->", hit["title"], "|", hit["heading"], "|", hit["url"])
    else:
        print("tools/call ->", call)

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    err = proc.stderr.read() if proc.stderr else ""
    print("stderr:", (err or "").strip()[:300])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
