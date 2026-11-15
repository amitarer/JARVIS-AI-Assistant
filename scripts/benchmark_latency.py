"""Measure actual local Qwen latency without microphone, personal DB or actions."""

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import secrets
import statistics
import sys
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jarvis.bootstrap import build_tool_registry
from jarvis.brain.ollama import OllamaProvider
from jarvis.core.controller import Controller
from jarvis.infrastructure.settings import load_settings
from jarvis.memory.database import Database
from jarvis.memory.repository import Repository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, choices=("before", "after"))
    parser.add_argument("--repeats", type=int, choices=range(1, 5), default=3)
    args = parser.parse_args()
    folder = ROOT / "data/verification/latency"
    folder.mkdir(parents=True, exist_ok=True)
    settings = load_settings(ROOT)
    rows = []
    original = OllamaProvider._response
    for repeat in range(args.repeats):
        for name, text in [("conversation", "Spiegami in una frase semplice che cos'è una sinapsi."),
                           ("clock", "Che ore sono?")]:
            database = Database(folder / f"{args.label}-{name}-{secrets.token_hex(4)}.sqlite3")
            database.initialize()
            repository = Repository(database)
            registry = build_tool_registry(settings, repository)
            controller = Controller(settings, repository, registry)
            events, requests, first_stream = [], [], []
            started = time.monotonic()
            original_execute = registry.execute

            def execute(call, *values, **keywords):
                if call.name != "get_current_datetime":
                    raise AssertionError("Benchmark only permits the fresh read-only clock tool")
                return original_execute(call, *values, **keywords)

            @contextmanager
            def response(provider, method, path, body, context):
                tick = time.monotonic()
                entry = {"method": method, "path": path, "body_bytes": len(json.dumps(body).encode()) if body else 0,
                         "tools": len(body.get("tools", [])) if body else 0, "stream": body.get("stream") if body else None}
                requests.append(entry)
                try:
                    with original(provider, method, path, body, context) as value:
                        yield value
                finally:
                    entry["seconds"] = round(time.monotonic() - tick, 4)

            def emit(event):
                events.append(event)
                if event.kind == "stream" and not first_stream:
                    first_stream.append(time.monotonic() - started)

            with patch.object(OllamaProvider, "_response", response), patch.object(registry, "execute", execute):
                controller.run({"kind": "voice", "text": text}, threading.Event(), emit, lambda *_: None)
            elapsed = time.monotonic() - started
            operations = repository.operations()
            succeeded = any(event.kind == "response" for event in events)
            row = {"scenario": name, "repeat": repeat, "seconds": round(elapsed, 4),
                   "first_stream_seconds": round(first_stream[0], 4) if first_stream else None,
                   "requests": requests, "inference_calls": sum(item["path"] == "/api/chat" for item in requests),
                   "operations": [{"tool": op["tool"], "status": op["status"]} for op in operations],
                   "succeeded": succeeded, "usage": [event.data for event in events if event.kind == "usage"]}
            if name == "clock":
                row["fresh_clock_verified"] = len(operations) == 1 and operations[0]["tool"] == "get_current_datetime" and operations[0]["status"] == "succeeded"
            rows.append(row)
            print(json.dumps(row), flush=True)
    medians = {name: round(statistics.median(row["seconds"] for row in rows if row["scenario"] == name), 4)
               for name in ("conversation", "clock")}
    report = {"label": args.label, "model": settings.ollama.model, "rows": rows, "median_seconds": medians,
              "microphone_used": False, "production_db_used": False, "actions_allowed": ["get_current_datetime"]}
    (folder / f"{args.label}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("MEDIANS", json.dumps(medians), flush=True)
    return 0 if all(row["succeeded"] and row.get("fresh_clock_verified", True) for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
