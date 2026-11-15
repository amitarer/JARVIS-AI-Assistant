"""Check real Qwen fast routing, including negations, without executing tools."""

import json
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jarvis.bootstrap import build_tool_registry
from jarvis.brain.ollama import OllamaProvider
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import load_settings
from jarvis.memory.database import Database
from jarvis.memory.repository import Repository
from jarvis.tools.system_information import OPERATIONS


def main():
    folder = ROOT / "data/verification/latency"
    folder.mkdir(parents=True, exist_ok=True)
    database = Database(folder / "routing.sqlite3")
    database.initialize()
    settings = load_settings(ROOT)
    registry = build_tool_registry(settings, Repository(database))
    schemas = [item for item in registry.schemas(for_model=True) if item["name"] in OPERATIONS
               or item["name"] in {"open_application", "open_resource", "start_autonomous_chat", "run_research"}]
    cases = [
        ("Spiegami in una frase che cos'è una sinapsi.", [], True),
        ("Che ore sono?", ["get_current_datetime"], False),
        ("Quale versione di Windows ho?", ["get_system_information"], False),
        ("Quali applicazioni sono aperte?", ["get_open_applications"], False),
        ("Aprimi Chrome.", ["open_application"], False),
        ("Apri YouTube.", ["open_resource"], False),
        ("Non aprire Chrome.", [], True),
        ("Come posso aprire Chrome?", [], True),
        ("Apri Chrome e dimmi che ore sono.", [], False),
        ("Leggi le ultime operazioni che hai eseguito.", [], False),
        ("Spiegami in modo molto dettagliato, in dieci paragrafi, come funziona una rete neurale.", [], False),
        ("Inizia a chattare con ChatGPT finché non dico stop.", ["start_autonomous_chat"], False),
    ]
    rows = []
    for text, expected, direct in cases:
        provider = OllamaProvider(settings.ollama)
        row = {"request": text}
        try:
            calls = provider.select_initial_tools([{"role": "user", "content": text}], schemas,
                                                  TaskContext("routing-verification", threading.Event(), 30))
            row.update(tools=[call.name for call in calls], direct_answer=provider.initial_answer is not None)
            row["passed"] = row["tools"] == expected and row["direct_answer"] == direct
        except Exception as exc:
            row.update(passed=False, error=type(exc).__name__ + ": " + str(exc))
        rows.append(row)
        print(json.dumps(row, ensure_ascii=True), flush=True)
    report = {"passed": all(row["passed"] for row in rows), "model": settings.ollama.model,
              "tools_executed": 0, "production_db_used": False, "cases": rows}
    (folder / "routing-verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
