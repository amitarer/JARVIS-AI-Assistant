"""Approved local, version-pinned npm install with lifecycle scripts disabled."""

import json
from pathlib import Path
import subprocess
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from development.bootstrap_tools import TOOLS, local_environment


def main():
    folder = TOOLS / "ruflo"
    folder.mkdir(exist_ok=True)
    locks = ROOT / "development/locks"
    pinned_lock = locks / "ruflo-package-lock.json"
    pinned_manifest = locks / "ruflo-package.json"
    if pinned_lock.is_file() and pinned_manifest.is_file():
        shutil.copyfile(pinned_manifest, folder / "package.json")
        shutil.copyfile(pinned_lock, folder / "package-lock.json")
        action = "ci"
    else:
        raise RuntimeError("Pinned Ruflo manifest and lockfile required; no automatic dependency resolution")
    expected = {
        "name": "jarvis-ruflo-tools", "version": "1.0.0", "private": True,
        "description": "Approved project-local tooling, separate from the Python environment",
        "dependencies": {"ruflo": "3.77.1"},
        # GHSA-mrhx-c7xc-m3w5: upstream's Zod 3 pin is affected. Keep this
        # project-local override explicit and verify the exposed MCP contracts.
        "overrides": {"zod": "4.6.6"},
    }
    manifest = json.loads((folder / "package.json").read_text(encoding="utf-8"))
    if manifest.get("dependencies") != expected["dependencies"] or manifest.get("overrides") != expected["overrides"]:
        raise RuntimeError("Unexpected Ruflo version or security override in pinned manifest")
    arguments = [str(TOOLS / "node/node.exe"), str(TOOLS / "node/node_modules/npm/bin/npm-cli.js"),
                 action, "--prefix", str(folder), "--ignore-scripts", "--omit=optional",
                 "--no-audit", "--no-fund", "--save-exact", "--registry", "https://registry.npmjs.org"]
    log = TOOLS / "ruflo-install.log"
    with log.open("w", encoding="utf-8") as output:
        result = subprocess.run(arguments, env=local_environment(), cwd=folder, stdout=output,
                                stderr=subprocess.STDOUT, timeout=600, creationflags=subprocess.CREATE_NO_WINDOW)
    print("NPM_EXIT", result.returncode, "LOG", log, flush=True)
    print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-18:]), flush=True)
    if result.returncode:
        return result.returncode
    scripts = []
    for package in (folder / "node_modules").rglob("package.json"):
        try:
            data = json.loads(package.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        lifecycle = {key: value for key, value in data.get("scripts", {}).items()
                     if key in {"preinstall", "install", "postinstall", "prepare"}}
        if lifecycle:
            scripts.append({"package": data.get("name"), "version": data.get("version"),
                            "file": str(package.relative_to(folder)), "scripts_not_executed": lifecycle})
    (TOOLS / "lifecycle-audit.json").write_text(json.dumps(scripts, indent=2), encoding="utf-8")
    print("Lifecycle scripts inventoried, not executed:", len(scripts), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
