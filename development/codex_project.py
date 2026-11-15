"""Start Codex with only this project's explicit MCP overrides, no global writes.

The CLI's MCP management commands need explicit overrides on this installation;
the IDE can read .codex/config.toml when the project is trusted and reloaded.
"""

from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from development.orchestrator.permissions import codex_executable, toml_value


def command(arguments):
    config = tomllib.loads((ROOT / ".codex/config.toml").read_text(encoding="utf-8"))
    server = config["mcp_servers"]["ruflo"]
    overrides = []
    for key, value in server.items():
        overrides.extend(("-c", "mcp_servers.ruflo." + key + "=" + toml_value(value)))
    return [str(codex_executable()), "-C", str(ROOT), *overrides, *arguments]


def main():
    return subprocess.call(command(sys.argv[1:]), cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
