"""Real Ollama integration checks, isolated SQLite, no canned model responses.

Option --open-notepad additionally asks the real model to open the allowlisted
Windows application. It leaves the application open and never sends messages.
"""

import argparse
import json
from pathlib import Path
import secrets
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.brain.ollama import OllamaProvider
from jarvis.core.controller import Controller
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import load_settings
from jarvis.memory.database import Database
from jarvis.memory.repository import Repository
from jarvis.security.approvals import ApprovalStore
from jarvis.security.policy import SecurityPolicy
from jarvis.tools.open_application import OpenApplicationTool
from jarvis.tools.read_operations import ReadOperationsTool
from jarvis.tools.registry import ToolRegistry


def main(open_notepad=False):
    settings = load_settings(ROOT)
    provider = OllamaProvider(settings.ollama)
    info = provider.check(TaskContext("qwen-preflight", threading.Event(), 15))
    nonce = "JARVIS-" + secrets.token_hex(4).upper()
    folder = ROOT / "data/verification"
    folder.mkdir(exist_ok=True)
    database = Database(folder / ("qwen-live-" + nonce + ".sqlite3"))
    database.initialize()
    repository = Repository(database)
    tools = ToolRegistry(SecurityPolicy(ApprovalStore()))
    tools.register(OpenApplicationTool(settings.applications))
    tools.register(ReadOperationsTool(repository))
    controller = Controller(settings, repository, tools)
    report = {"provider": info, "nonce": nonce, "test_database": str(database.path), "requests": [], "checks": {}}

    def request(text):
        events = []
        started = time.monotonic()
        controller.run({"kind": "chat", "text": text}, threading.Event(), events.append, lambda *_: None)
        answers = [event.data for event in events if event.kind == "response"]
        item = {"request": text, "answer": answers[-1] if answers else None,
                "seconds": round(time.monotonic() - started, 2),
                "stream_events": sum(event.kind == "stream" for event in events),
                "usage": [event.data for event in events if event.kind == "usage"],
                "notices": [event.data for event in events if event.kind == "notice"],
                "task_status": repository.tasks()[0]["status"]}
        report["requests"].append(item)
        print(json.dumps(item, ensure_ascii=True), flush=True)
        return item

    first = request(f"Il mio codice di prova per questa conversazione è {nonce}. Salutami in italiano e ripeti esattamente il codice in una sola frase. Non eseguire operazioni.")
    report["checks"]["real_model_echoed_random_nonce"] = nonce in (first["answer"] or "") and bool(first["usage"])
    second = request("Qual è il codice di prova che ti ho appena comunicato? Riportalo esattamente, senza aggiungere altro.")
    report["checks"]["sqlite_context_recalled_nonce"] = nonce in (second["answer"] or "")
    third = request("Hai inviato una mail al professore? Controlla il registro delle operazioni. Non inviare nulla.")
    report["checks"]["no_email_send_tool_or_success_record"] = all(row["tool"] in {"read_operations"} for row in repository.operations())
    failure = request("/apri applicazione_non_autorizzata")
    report["checks"]["unauthorized_app_failed_without_success_reply"] = failure["answer"] is None and failure["task_status"] == "failed"
    if open_notepad:
        opened = request("Apri Blocco note utilizzando lo strumento open_application con application_id blocco_note. Non dichiarare verificata la finestra.")
        launches = [row for row in repository.operations() if row["tool"] == "open_application" and row["status"] == "succeeded"]
        report["checks"]["real_notepad_process_recorded"] = bool(launches and json.loads(launches[0]["evidence_json"]).get("process_created"))
        report["checks"]["window_verification_not_invented"] = bool(launches and json.loads(launches[0]["evidence_json"]).get("window_verified") is False)
    usages = [usage for request in report["requests"] for usage in request["usage"]]
    report["checks"]["streaming_final_content"] = any(request["stream_events"] > 1 for request in report["requests"])
    report["checks"]["thinking_false_requested"] = bool(usages) and all(usage.get("thinking_disabled_requested") for usage in usages)
    report["checks"]["no_reasoning_in_saved_answers"] = all("<think" not in message.content.casefold() and "</think" not in message.content.casefold()
                                                             for message in repository.messages() if message.role == "assistant")
    report["passed"] = all(report["checks"].values())
    path = folder / "qwen-integration.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": report["checks"], "report": str(path)}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open-notepad", action="store_true")
    args = parser.parse_args()
    raise SystemExit(main(args.open_notepad))
