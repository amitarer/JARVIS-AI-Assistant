"""Live IDE MCP wire verification. No model invocation or task dispatch."""

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from development.codex_project import command
from development.orchestrator.permissions import STATE


def main():
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "jarvis-verification", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "agent_list", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "agent_execute", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "jarvis_development_status", "arguments": {}}},
    ]
    process = subprocess.run([sys.executable, "-B", str(ROOT / "development/ruflo_mcp_server.py")],
                             input="".join(json.dumps(row) + "\n" for row in messages),
                             text=True, capture_output=True, timeout=90, cwd=ROOT)
    rows = {row["id"]: row for line in process.stdout.splitlines() if line.startswith("{") for row in [json.loads(line)]}
    assert process.returncode == 0, process.stderr[-2000:]
    assert rows[1]["result"]["serverInfo"]["name"] == "jarvis-ruflo-readonly", rows
    names = sorted(tool["name"] for tool in rows[2]["result"]["tools"])
    assert len(names) == 7 and "agent_execute" not in names, names
    assert "result" in rows[3] and rows[4]["error"]["code"] == -32601, rows
    observed = json.loads(rows[5]["result"]["content"][0]["text"])
    expected = json.loads((STATE / "status.json").read_text(encoding="utf-8"))
    assert observed["run_id"] == expected["run_id"] and observed["status"] == expected["status"]
    cli = subprocess.run(command(["mcp", "get", "ruflo", "--json"]), capture_output=True, text=True, cwd=ROOT, timeout=30)
    assert cli.returncode == 0, cli.stderr
    configured = json.loads(cli.stdout)
    assert set(configured["enabled_tools"]) == set(names), configured
    report = {"passed": True, "tools": names, "status_call_passed": True, "execution_tool_rejected": True,
              "actual_runner_status": observed["status"], "cli_explicit_project_config_verified": True,
              "ide_reload_needed": True, "model_executors_started": 0}
    (STATE / "ide-mcp-verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
