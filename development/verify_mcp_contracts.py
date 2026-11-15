"""Live tests of the limited MCP surface; metadata probes are not AI agents."""

import json
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from development.orchestrator.permissions import STATE
from development.orchestrator.services import start_ruflo
from development.orchestrator.windows_job import WindowsJob


def main():
    folder = STATE / "mcp-contracts"
    folder.mkdir(parents=True, exist_ok=True)
    report = {"metadata_probe_only": True, "model_executors_started": 0, "checks": {}}
    with WindowsJob() as job:
        client, identity = start_ruflo(job, folder)
        try:
            report["server"] = identity["server"]
            swarm = client.call("swarm_init", {"topology": "hierarchical", "maxAgents": 1, "strategy": "specialized"})
            swarm_id = swarm["swarmId"]
            record = client.call("agent_spawn", {"agentType": "contract-probe", "name": "Metadata probe; no executor",
                                                  "model": "inherit", "swarmId": swarm_id})
            identifier = record["agentId"]
            report["checks"]["metadata_not_reported_as_execution"] = record.get("status") == "registered"
            refused = False
            try:
                client.call("agent_spawn", {"agentType": "over-cap-probe", "model": "inherit", "swarmId": swarm_id})
            except RuntimeError as exc:
                refused = "full" in str(exc).lower()
            report["checks"]["swarm_capacity_enforced"] = refused
            client.call("agent_update", {"agentId": identifier, "status": "busy"})
            report["checks"]["metadata_status_update"] = client.call("agent_status", {"agentId": identifier}).get("status") == "busy"
            client.call("agent_terminate", {"agentId": identifier})
            report["checks"]["metadata_terminated"] = client.call("agent_status", {"agentId": identifier}).get("status") == "terminated"
            autopilot = client.call("autopilot_status")
            report["checks"]["autopilot_disabled"] = autopilot.get("enabled") is False
            report["checks"]["model_execution_not_advertised"] = "agent_execute" not in client.tools
            client.call("swarm_shutdown", {"swarmId": swarm_id})
        finally:
            client.close()
            job.terminate()
            client.finish_io()
    report["passed"] = all(report["checks"].values())
    (folder / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
