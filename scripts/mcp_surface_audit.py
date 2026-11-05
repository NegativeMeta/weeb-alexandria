"""Audit the Weeb Alexandria MCP surface over stdio, stdlib only.

Handshake + ``tools/list`` + ``tools/call`` with per-call latency and payload
size, so "the MCP works" is a measurement instead of a feeling. Launches the
project's own ``run.bat``, which is exactly what Hermes launches, so the venv
and the ``TAGLIB_DB``/``SEARCH_DB`` env vars apply.

Usage
-----
    .venv/Scripts/python.exe scripts/mcp_surface_audit.py
    .venv/Scripts/python.exe scripts/mcp_surface_audit.py --repeat 2 --preview 600
    .venv/Scripts/python.exe scripts/mcp_surface_audit.py --calls my_calls.json

``--calls`` accepts ``[{"name": "...", "args": {...}}, ...]``; when omitted the
default battery below exercises every exposed tool once. Exit code is 0 only
when every listed tool answered without error, so it can gate maintenance work.

Adapted from the Hermes ``mcp-tool-surface-audit`` skill harness.
"""
from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMMAND = f'cmd.exe /d /c "{REPO_ROOT / "run.bat"}"'

# One cheap, deterministic call per exposed tool.
DEFAULT_CALLS = [
    {"name": "get_sources_status", "args": {}},
    {"name": "search_knowledge", "args": {"query": "hatsune miku", "limit": 3}},
    {"name": "get_knowledge", "args": {"tag": "hatsune_miku",
                                       "include_relations": False}},
    {"name": "search_characters", "args": {"q": "gawr gura"}},
    {"name": "search_characters", "args": {"hair_color": "white",
                                           "scope": "all", "page": 1}},
    {"name": "get_character", "args": {"character": "hatsune_miku"}},
    {"name": "resolve_character", "args": {"query": "Anya Forger"}},
]


class MCPClient:
    def __init__(self, command: str, cwd: str | None = None) -> None:
        self.p = subprocess.Popen(
            command, shell=True, cwd=cwd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        self.q: queue.Queue = queue.Queue()
        self.stderr_lines: list[str] = []
        self._next_id = 0
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        for line in self.p.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self.q.put(json.loads(line))
            except ValueError:
                pass  # banners / non-JSON noise

    def _read_stderr(self) -> None:
        for line in self.p.stderr:
            self.stderr_lines.append(line.rstrip())

    def notify(self, method: str, params: dict | None = None) -> None:
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def request(self, method: str, params: dict | None = None,
                timeout: int = 180) -> dict:
        self._next_id += 1
        rid = self._next_id
        msg: dict = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                reply = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            if reply.get("id") == rid:
                return reply
        raise TimeoutError(f"{method} (id={rid}) timed out after {timeout}s")

    def call_tool(self, name: str, args: dict, timeout: int = 300
                  ) -> tuple[dict, float, bool]:
        t0 = time.time()
        reply = self.request("tools/call", {"name": name, "arguments": args},
                             timeout=timeout)
        elapsed = time.time() - t0
        if "error" in reply:
            return {"error": reply["error"]}, elapsed, False
        result = reply.get("result", {})
        text = "".join(
            chunk.get("text", "")
            for chunk in (result.get("content") or [])
            if isinstance(chunk, dict)
        )
        return {"text": text, "isError": bool(result.get("isError"))}, elapsed, True

    def close(self) -> None:
        try:
            self.p.stdin.close()
        except Exception:
            pass
        self.p.terminate()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--command", default=DEFAULT_COMMAND,
                    help="launch command line (default: this repo's run.bat)")
    ap.add_argument("--cwd", default=str(REPO_ROOT))
    ap.add_argument("--calls", default=None,
                    help="JSON file with [{\"name\":..,\"args\":{..}}]")
    ap.add_argument("--repeat", type=int, default=1, help="runs per call (2 = cold + warm)")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--preview", type=int, default=300)
    args = ap.parse_args(argv)

    client = MCPClient(args.command, cwd=args.cwd)
    try:
        t0 = time.time()
        init = client.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "weeb-alexandria-surface-audit", "version": "1"},
        }, timeout=120)
        print(f"initialize: {time.time() - t0:.2f}s -> "
              f"{json.dumps(init.get('result', init).get('serverInfo', {}), ensure_ascii=False)}")
        client.notify("notifications/initialized", {})

        listed = client.request("tools/list", timeout=60)["result"]["tools"]
        print(f"tools/list: {len(listed)} tools")
        required: dict[str, list[str]] = {}
        for tool in listed:
            schema = tool.get("inputSchema") or {}
            props = list((schema.get("properties") or {}).keys())
            required[tool["name"]] = schema.get("required") or []
            print(f"  - {tool['name']}({', '.join(props)}) required={schema.get('required') or []}")
            print(f"      {(tool.get('description') or '').strip().splitlines()[0][:160]}")

        calls = DEFAULT_CALLS
        if args.calls:
            with open(args.calls, encoding="utf-8") as fh:
                calls = json.load(fh)

        ok = err = 0
        for spec in calls:
            name, call_args = spec["name"], spec.get("args") or {}
            if name not in required:
                print(f"\n[X] {name}: not in tools/list")
                err += 1
                continue
            missing = [key for key in required[name] if key not in call_args]
            if missing:
                print(f"\n[-] {name}: skipped, missing required {missing}")
                continue
            for run in range(1, args.repeat + 1):
                try:
                    payload, elapsed, delivered = client.call_tool(
                        name, call_args, timeout=args.timeout)
                except Exception as exc:  # timeout / transport
                    print(f"\n[X] {name}{call_args} -> {type(exc).__name__}: {exc}")
                    err += 1
                    continue
                size = len(payload.get("text", "")) if delivered else 0
                good = delivered and not payload.get("isError")
                print(f"\n[{'OK' if good else 'X'}] {name}{call_args} "
                      f"run{run} {elapsed:.2f}s payload={size}B")
                print("    " + str(payload.get("text") or payload.get("error"))[: args.preview]
                      .replace("\n", " "))
                if good:
                    ok += 1
                else:
                    err += 1

        print(f"\nsummary: {ok} ok, {err} errors, {len(listed)} tools listed")
        if client.stderr_lines:
            print("stderr tail:")
            print("\n".join(client.stderr_lines[-10:]))
        return 0 if err == 0 else 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
