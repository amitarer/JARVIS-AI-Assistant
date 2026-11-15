"""Compare real local Qwen public answers; every desktop effect is denied."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import re
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jarvis.bootstrap import build_tool_registry
from jarvis.core.models import UserError
from jarvis.infrastructure.settings import load_settings
from tests.support import make_controller, temporary_project


def valid_schedule(answer):
    answer=answer.replace("*", "")
    rows = re.findall(r"\b([ABCD])\s*:\s*L([12])\s*,\s*(\d+)\s*[-–]\s*(\d+)", answer, re.I)
    # Also accept ordinary prose: A (0-6) on L1; B (6-10) and C (0-5) on L2.
    # Every extracted interval still undergoes the same numerical checks.
    for segment in re.split(r"[;\n]",answer):
        workers=set(re.findall(r"\bL([12])\b",segment,re.I))
        if len(workers)==1:
            worker=next(iter(workers))
            rows.extend((name,worker,start,end) for name,start,end in re.findall(
                r"\b([ABCD])\s*\(\s*(\d+)\s*[-–]\s*(\d+)\s*\)",segment,re.I))
    rows=list(set((name.upper(),worker,start,end) for name,worker,start,end in rows))
    if len(rows) != 4 or len({row[0].upper() for row in rows}) != 4:
        return False
    schedule = {name.upper(): (int(worker), int(start), int(end)) for name, worker, start, end in rows}
    durations = {"A":6, "B":4, "C":5, "D":3}
    if any(start < 0 or end-start != durations[name] for name,(worker,start,end) in schedule.items()):
        return False
    if any(schedule[parent][2] > schedule[child][1] for parent,child in (("A","B"),("B","D"),("C","D"))):
        return False
    for worker in (1,2):
        intervals=sorted((start,end) for assigned,start,end in schedule.values() if assigned==worker)
        if any(intervals[i][1] > intervals[i+1][0] for i in range(len(intervals)-1)):
            return False
    return max(end for _,_,end in schedule.values()) == 13

CASES = [
    ("exact_arithmetic", "Quanto fa esattamente 987654321 moltiplicato per 123456789? Dammi l'intero completo.",
     lambda a: "121932631112635269" in re.sub(r"[\s.,]", "", a)),
    ("truth_constraints", "Un solo colpevole tra Ada, Berto, Ciro e Dario. Esattamente due dichiarazioni sono vere. "
     "Ada: il colpevole e' Berto o Ciro. Berto: il colpevole non e' Dario. Ciro: il colpevole e' Ada. "
     "Dario: Ada e Berto dicono entrambi il vero. Chi e' il colpevole? Spiega brevemente come controlli i vincoli.",
     lambda a: bool(re.search(r"colpevole\s+(?:è|e['’])\s+Ada\b", a.replace("*", ""), re.I))
               and not re.search(r"ma aspetta|ricalcolo",a,re.I)),
    ("dependency_schedule", "Due lavoratori identici. A dura 6 minuti; B dura 4 e inizia solo dopo A; "
     "C dura 5 ed e' indipendente; D dura 3 e inizia solo dopo B e C. Ogni attivita' occupa un lavoratore, "
     "senza interruzioni. Qual e' il tempo minimo totale e un calendario valido?",
     valid_schedule),
    ("simple_conversation", "Ciao Jarvis.", lambda a: bool(a.strip())),
]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--label", choices=("before", "after"), required=True)
    args = p.parse_args()
    rows = []
    for name, request, check in CASES:
        with temporary_project() as directory:
            c = make_controller(Path(directory))
            c.settings = replace(c.settings, ollama=load_settings(ROOT).ollama)
            c.tools = build_tool_registry(c.settings, c.repository)
            execute = c.execute_tool
            def safe_execute(call, *values, **keywords):
                if call.name != "calculate":
                    raise UserError("Benchmark refuses every non-calculator operation.")
                return execute(call, *values, **keywords)
            c.execute_tool = safe_execute
            events = []
            started = time.monotonic()
            c.run({"kind": "chat", "text": request}, threading.Event(), events.append, lambda *_: None)
            task = c.repository.tasks()[0]
            answer = task["result_text"]
            row = {"name": name, "passed": task["status"] == "succeeded" and check(answer),
                   "seconds": round(time.monotonic() - started, 3), "answer": answer, "error": task["error_text"],
                   "tools": [op["tool"] for op in c.repository.operations()],
                   "usage": [e.data for e in events if e.kind == "usage"]}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=True), flush=True)
    folder = ROOT / "data/verification/reasoning"
    folder.mkdir(parents=True, exist_ok=True)
    report = {"label": args.label, "model": c.settings.ollama.model, "passed": sum(r["passed"] for r in rows),
              "total": len(rows), "rows": rows, "personal_database_opened": False, "external_effects": 0}
    (folder / (args.label + ".json")).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if all(row["passed"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
