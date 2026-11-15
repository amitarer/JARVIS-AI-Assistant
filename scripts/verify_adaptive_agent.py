"""Real Qwen recovers from a file moved during a read, inside an isolated fixture."""

from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from jarvis.core.controller import Controller
from jarvis.core.models import UserError
from jarvis.infrastructure.settings import load_settings
from jarvis.memory.database import Database
from jarvis.memory.repository import Repository
from jarvis.security.approvals import ApprovalStore
from jarvis.security.policy import SecurityPolicy
from jarvis.tools.pc import InspectFilesTool
from jarvis.tools.registry import ToolRegistry


def main():
    base=ROOT/"data/test-runs"
    base.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="adaptive-",dir=base) as directory:
        root=Path(directory).resolve()
        note=root/"appunti.txt"
        note.write_text("Il codice di verifica del documento e ORIONE-742. La revisione richiesta e la numero 19.",encoding="utf-8")
        moved=[False]
        class MovingFileInspection(InspectFilesTool):
            def validate(self,args):
                arguments=super().validate(args)
                if not Path(arguments["path"]).resolve().is_relative_to(root):
                    raise UserError("Questa verifica puo' leggere soltanto la propria cartella di prova.")
                return arguments
            def execute(self,args,context):
                if args["action"]=="read_text" and Path(args["path"])==note and not moved[0]:
                    note.rename(root/"appunti-aggiornati.txt")
                    moved[0]=True
                return super().execute(args,context)
        settings=replace(load_settings(ROOT),root=root)
        database=Database(root/"data/session.sqlite3");database.initialize()
        repository=Repository(database)
        registry=ToolRegistry(SecurityPolicy(ApprovalStore()));registry.register(MovingFileInspection())
        controller=Controller(settings,repository,registry)
        events=[]
        def emit(event):
            events.append(event)
            if event.kind=="action":print("TOOL",event.data["tool"],flush=True)
            if event.kind in {"notice","response"}:print(event.kind,str(event.data)[:600],flush=True)
        started=time.monotonic()
        controller.run({"kind":"chat","text":f"Leggi appunti.txt nella cartella {root} e dimmi codice di verifica e numero di revisione. Se il file e stato spostato o rinominato cerca nella stessa cartella e leggi il documento aggiornato."},
                       threading.Event(),emit,lambda *_:None)
        operations=repository.operations(limit=50)
        answer=next((e.data for e in events if e.kind=="response"),"")
        result={"passed":moved[0] and "ORIONE-742" in answer and "19" in answer and any(o["status"]=="failed" for o in operations)
                       and repository.tasks()[0]["status"]=="succeeded",
                "real_qwen":True,"real_filesystem":True,"fault_injected":"fixture file renamed at first read",
                "external_writes":False,"operations":[{"tool":o["tool"],"status":o["status"]} for o in reversed(operations)],
                "answer":answer,"seconds":round(time.monotonic()-started,2)}
        (ROOT/"data/verification/adaptive-agent.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(result,ensure_ascii=False),flush=True)
        return 0 if result["passed"] else 1


if __name__=="__main__":
    raise SystemExit(main())
