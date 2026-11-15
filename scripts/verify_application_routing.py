"""Real Qwen routing regressions, with optional Chrome launches and isolated SQLite."""

import argparse
import json
from pathlib import Path
import secrets
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.bootstrap import build_tool_registry
from jarvis.brain.ollama import OllamaProvider
from jarvis.core.controller import Controller
from jarvis.core.models import UserError
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import load_settings
from jarvis.memory.database import Database
from jarvis.memory.repository import Repository
from jarvis.tools.system_information import OPERATIONS


def main(open_chrome=False):
    settings = load_settings(ROOT)
    folder = ROOT / "data/verification"
    folder.mkdir(parents=True, exist_ok=True)
    database = Database(folder / ("application-routing-" + secrets.token_hex(4) + ".sqlite3"))
    database.initialize()
    repository = Repository(database)
    registry = build_tool_registry(settings, repository)
    controller = Controller(settings, repository, registry)
    provider = OllamaProvider(settings.ollama)
    schemas = [schema for schema in registry.schemas(for_model=True)
               if schema["name"] in OPERATIONS or schema["name"] == "open_application"]
    report = {"routes": [], "requests": [], "passed": False, "database": str(database.path)}
    cases = [("Aprimi Chrome", "open_application"), ("Apri microm", "open_application"),
             ("Avvia Spotify", "open_application"), ("Apri la Calcolatrice", "open_application"),
             ("Apri Chrome e dimmi che ore sono", None), ("Che ore sono?", "get_current_datetime"),
             ("Quali applicazioni sono aperte?", "get_open_applications"),
             ("Non aprire Chrome", None), ("Come posso aprire Chrome?", None), ("Ciao", None)]
    try:
        for text, expected in cases:
            messages = [{"role": "user", "content": "Che ore sono?"},
                        {"role": "assistant", "content": "Sono le 12:00. Finestre aperte: Chrome."},
                        {"role": "user", "content": text}]
            calls = provider.select_initial_tools(messages, schemas, TaskContext("route-check", threading.Event(), 30))
            names = [call.name for call in calls]
            passed = not names if expected is None else names == [expected]
            item = {"request": text, "tools": names, "passed": passed}
            report["routes"].append(item)
            print(json.dumps(item, ensure_ascii=True), flush=True)

        if open_chrome:
            repository.add_message("user", "Che ore sono? Quali finestre sono aperte?")
            repository.add_message("assistant", "Sono le 12:00. Finestre aperte: Chrome.")
            for text, expected_tool in [("Aprimi Chrome", "open_application"),
                                        ("Che ore sono?", "get_current_datetime"),
                                        ("Apri microm", "open_application")]:
                def before_tool(name, context):
                    if name not in {"open_application", "get_current_datetime"}:
                        raise UserError("La prova consente solo Chrome e la lettura dell'orario.")
                    if name == "open_application":
                        operation = next(row for row in repository.operations(limit=50)
                                         if row["task_id"] == context.task_id and row["tool"] == name)
                        arguments = json.loads(operation["arguments_json"])
                        app = registry._tools[name].catalog.resolve(arguments["application_id"], context)
                        if app.identifier != "chrome":
                            raise UserError("La prova permette soltanto Google Chrome.")

                events = []
                started = time.monotonic()
                controller.run({"kind": "chat", "text": text}, threading.Event(), events.append, lambda *_: None, before_tool)
                task = repository.tasks()[0]
                operations = [row for row in repository.operations(limit=50) if row["task_id"] == task["id"]]
                names = [row["tool"] for row in reversed(operations)]
                answers = [event.data for event in events if event.kind == "response"]
                passed = task["status"] == "succeeded" and any(
                    row["tool"] == expected_tool and row["status"] == "succeeded" for row in operations)
                if expected_tool == "open_application":
                    passed = passed and not any(name in OPERATIONS for name in names)
                item = {"request": text, "tools": names, "answer": answers[-1] if answers else None,
                        "status": task["status"], "passed": passed, "seconds": round(time.monotonic() - started, 2)}
                report["requests"].append(item)
                print(json.dumps(item, ensure_ascii=True), flush=True)
        report["passed"] = all(item["passed"] for item in report["routes"] + report["requests"])
    finally:
        path = folder / "application-routing.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "report": str(path)}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open-chrome", action="store_true", help="Verifica anche due avvii reali di Chrome tramite il controller")
    args = parser.parse_args()
    raise SystemExit(main(args.open_chrome))
