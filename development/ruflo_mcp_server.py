"""Read-only MCP bridge for Codex IDE, with MXC and owned-process limits.

The stdin gate enforces its tool allowlist independently of upstream discovery.
No agent execution, registration, task mutation or autopilot activation is exposed.
"""

import json
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from development.orchestrator.permissions import STATE
from development.orchestrator.services import READ_TOOLS, start_ruflo
from development.orchestrator.windows_job import WindowsJob

MAX_LINE = 2_000_000
STATUS_TOOL = {"name": "jarvis_development_status", "description": "Read the actual bounded JARVIS development runner's latest report; does not start agents.",
               "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}


def development_status():
    path = STATE / "status.json"
    if not path.is_file():
        return {"status": "not_started", "continuous": False}
    if path.stat().st_size > MAX_LINE:
        raise ValueError("Runner status exceeds the response limit")
    return json.loads(path.read_text(encoding="utf-8"))


def permitted(message):
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return False
    method = message.get("method")
    if method == "tools/call":
        return isinstance(message.get("params"), dict) and message["params"].get("name") in (*READ_TOOLS, STATUS_TOOL["name"])
    return method in {"initialize", "notifications/initialized", "tools/list", "server/discover", "ping",
                      "notifications/cancelled", "notifications/progress"}


def main():
    folder = STATE / "ide-mcp"
    folder.mkdir(parents=True, exist_ok=True)
    output_lock = threading.Lock()

    def emit(value):
        with output_lock:
            sys.stdout.write(json.dumps(value, ensure_ascii=True) + "\n")
            sys.stdout.flush()

    # We use the verified client handshake locally, then expose discovery/status
    # through a small second MCP endpoint; no raw upstream mutation is forwarded.
    with WindowsJob(memory_mib=1024, cpu_percent=10) as job:
        client, identity = start_ruflo(job, folder, readonly=True)
        try:
            while True:
                raw = sys.stdin.buffer.readline(MAX_LINE + 1)
                if not raw:
                    break
                if len(raw) > MAX_LINE:
                    emit({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "MCP request too large"}})
                    return 1
                try:
                    message = json.loads(raw)
                except ValueError:
                    emit({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid JSON"}})
                    continue
                identifier = message.get("id") if isinstance(message, dict) else None
                if not permitted(message):
                    if identifier is not None:
                        emit({"jsonrpc": "2.0", "id": identifier, "error": {"code": -32601, "message": "Tool or method is outside the JARVIS read-only MCP allowlist"}})
                    continue
                method = message["method"]
                if identifier is None:
                    continue
                try:
                    if method == "initialize":
                        result = {"protocolVersion": "2025-06-18", "serverInfo": {"name": "jarvis-ruflo-readonly", "version": "1.0.0"},
                                  "capabilities": {"tools": {}}}
                    elif method == "server/discover":
                        # Let a newer client negotiate down through initialize.
                        emit({"jsonrpc": "2.0", "id": identifier, "error": {"code": -32601, "message": "Use MCP initialize with protocol 2025-06-18"}})
                        continue
                    elif method == "tools/list":
                        result = {"tools": [*identity["tools"], STATUS_TOOL]}
                    elif method == "tools/call":
                        params = message["params"]
                        if params["name"] == STATUS_TOOL["name"]:
                            if params.get("arguments", {}):
                                raise ValueError("Status does not accept arguments or file paths")
                            value = development_status()
                        else:
                            value = client.call(params["name"], params.get("arguments", {}))
                        result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=True)}]}
                    elif method == "ping":
                        result = {}
                    else:
                        result = {}
                    emit({"jsonrpc": "2.0", "id": identifier, "result": result})
                except Exception as exc:
                    emit({"jsonrpc": "2.0", "id": identifier, "error": {"code": -32603, "message": str(exc)[:1000]}})
        finally:
            client.close()
            job.terminate()
            client.finish_io()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
