"""Launch only the pinned, locally installed Ruflo server inside MXC."""

from pathlib import Path

from .permissions import STATE, TOOLS, sandbox_command
from .mcp_client import RufloClient

READ_TOOLS = ("swarm_status", "swarm_health", "agent_list", "agent_status", "autopilot_status", "autopilot_progress")
COORDINATION_TOOLS = (*READ_TOOLS, "swarm_init", "swarm_shutdown", "agent_spawn", "agent_update", "agent_terminate")


def start_ruflo(job, log_dir, *, readonly=False, checkpoint=lambda: None):
    workspace = STATE / "coordination"
    workspace.mkdir(parents=True, exist_ok=True)
    package_boundary = workspace / "package.json"
    if not package_boundary.exists():
        package_boundary.write_text('{"name":"jarvis-coordination-state","private":true}', encoding="utf-8")
    selected = READ_TOOLS if readonly else COORDINATION_TOOLS
    node = TOOLS / "node/node.exe"
    entry = TOOLS / "ruflo/node_modules/ruflo/bin/ruflo.js"
    compatibility = Path(__file__).with_name("ruflo_realpath.cjs")
    if not node.is_file() or not entry.is_file():
        raise RuntimeError("Approved local Ruflo installation is missing")
    command, env = sandbox_command([node, "--preserve-symlinks", "--preserve-symlinks-main",
                                   "--require", compatibility, entry,
                                   "mcp", "start", "--tools", ",".join(selected)], workspace,
                                   name="mcp-read" if readonly else "mcp-runner",
                                   extra_read=(TOOLS / "node", TOOLS / "ruflo", compatibility,
                                               compatibility.with_name("package.json")))
    env.update(CLAUDE_FLOW_MCP_TOOLS=",".join(selected), RUFLO_PROVIDER="ollama",
               OLLAMA_BASE_URL="http://127.0.0.1:11434", OLLAMA_DEFAULT_MODEL="qwen3.5:9b")
    client = RufloClient(job.spawn(command, cwd=workspace, env=env), Path(log_dir), checkpoint=checkpoint)
    identity = client.initialize()
    advertised = set(client.tools)
    if set(selected) != advertised:
        raise RuntimeError(f"Ruflo catalog differs from its allowlist: {set(selected) ^ advertised}")
    if "agent_execute" in advertised:
        raise RuntimeError("The metadata server must not expose model execution")
    return client, identity


def main():
    import json
    from .windows_job import WindowsJob
    folder = STATE / "mcp-preflight"
    folder.mkdir(parents=True, exist_ok=True)
    with WindowsJob() as job:
        client, identity = start_ruflo(job, folder)
        (folder / "catalog.json").write_text(json.dumps(identity, indent=2), encoding="utf-8")
        result = {"server": identity["server"], "tools": list(client.tools),
                  "agents": client.call("agent_list"), "job_limits": job.sample(), "passed": True}
        (folder / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        client.close()
        print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
