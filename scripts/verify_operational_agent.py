"""Real local Qwen decisions in an isolated fixture; no personal accounts or sends."""

from dataclasses import replace
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.bootstrap import build_tool_registry
from jarvis.brain.ollama import OllamaProvider
from jarvis.core.models import UserError
from jarvis.infrastructure.settings import load_settings
from tests.support import make_controller, temporary_project


def main():
    report = {"provider": "real_local_ollama", "personal_database_opened": False,
              "external_messages_sent": 0, "native_whatsapp_automation_verified": False, "cases": []}
    for name in ("missing_whatsapp_details", "multi_step_reads"):
        with temporary_project() as directory:
            controller = make_controller(Path(directory))
            controller.settings = replace(controller.settings, ollama=load_settings(ROOT).ollama)
            controller.tools = build_tool_registry(controller.settings, controller.repository)
            # Fail before every effect, including accidental model-generated GUI actions.
            allowed = {"whatsapp_contact", "inspect_files", "get_current_datetime"}
            original = controller.execute_tool
            executed = []

            def read_only(call, *args, **kwargs):
                if call.name not in allowed or (call.name == "whatsapp_contact"
                        and json.loads(call.arguments_json).get("action") != "lookup"):
                    raise UserError("Verification refuses all desktop and messaging effects: " + call.name)
                executed.append(call.name)
                return original(call, *args, **kwargs)

            controller.execute_tool = read_only
            if name == "missing_whatsapp_details":
                request = "Apri WhatsApp e scrivi a mio padre."
            else:
                first, second = Path(directory) / "one.txt", Path(directory) / "two.txt"
                first.write_text("Codice del primo file: ALFA-17", encoding="utf-8")
                second.write_text("Codice del secondo file: BETA-29", encoding="utf-8")
                request = f"Leggi entrambi i file {first} e {second}, poi controlla l'ora attuale. Dimmi i due codici e l'ora. Lavora in silenzio."
            events = []
            started = time.monotonic()
            controller.run({"kind": "chat", "text": request}, threading.Event(), events.append, lambda *_: None)
            task = controller.repository.tasks()[0]
            passed = (task["status"] == "waiting_input" and "?" in task["result_text"] if name == "missing_whatsapp_details" else
                      task["status"] == "succeeded" and executed.count("inspect_files") == 2
                      and "get_current_datetime" in executed and "ALFA-17" in task["result_text"] and "BETA-29" in task["result_text"])
            case = {"name": name, "passed": passed, "seconds": round(time.monotonic() - started, 2),
                    "status": task["status"], "tools": executed, "answer": task["result_text"], "error": task["error_text"]}
            report["cases"].append(case)
            print(json.dumps(case, ensure_ascii=True), flush=True)
    report["passed"] = all(case["passed"] for case in report["cases"])
    destination = ROOT / "data/verification/operational-agent.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
