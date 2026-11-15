"""Inspect the existing Ollama server with the fusion branch; never generate."""

import argparse
import json
from pathlib import Path
import sys
import threading
import time

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from jarvis.brain.ollama import OllamaProvider
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import load_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    args = parser.parse_args()
    root = args.project_root.resolve()
    settings = load_settings(root)
    provider = OllamaProvider(settings.ollama)
    original = provider._json
    requests = []

    def read_only(method, path, body, context):
        if (method, path) not in {("GET", "/api/tags"), ("POST", "/api/show"), ("GET", "/api/ps")}:
            raise AssertionError("Fusion verification only permits model metadata")
        requests.append({"method": method, "path": path})
        return original(method, path, body, context)
    provider._json = read_only
    started = time.monotonic()
    status = provider.inventory(TaskContext("fusion-inventory", threading.Event(), 10))
    value = status["local_inventory"]
    report = {"passed": value["configured_model"] == settings.ollama.model and value["runtime_probe_available"],
              "seconds": round(time.monotonic() - started, 4), "source_module": str(SOURCE / "jarvis/brain/ollama.py"),
              "requests": requests, "generation_requests": 0, "model_mutations": 0, "personal_database_opened": False,
              "inventory": value}
    folder = root / ".development-state/fusion-verification"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "ollama-inventory.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
