"""Real public discovery, source reads, local Qwen and Qt PDF; no account writes."""

import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from jarvis.brain.ollama import OllamaProvider
from jarvis.core.controller import Controller
from jarvis.core.models import ToolCall
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import load_settings
from jarvis.memory.database import Database
from jarvis.memory.repository import Repository
from jarvis.research.executor import ResearchExecutor
from jarvis.research.service import ResearchServices
from jarvis.security.approvals import ApprovalStore
from jarvis.security.policy import SecurityPolicy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.research import RunResearchTool,ResearchOperationTool


def main():
    app = QApplication.instance() or QApplication([])
    for font in ("segoeui.ttf","segoeuib.ttf"):
        QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts")/font))
    settings = load_settings(ROOT)
    folder = ROOT/"data/verification"
    folder.mkdir(parents=True,exist_ok=True)
    database = Database(folder/"research-test.sqlite3")
    database.initialize()
    repository = Repository(database)
    registry = ToolRegistry(SecurityPolicy(ApprovalStore()))
    services = ResearchServices(ROOT)
    registry.register(RunResearchTool())
    for operation in ("search","fetch","pdf","chatgpt","google_docs"):
        registry.register(ResearchOperationTool(services,operation))
    controller = Controller(settings,repository,registry)
    task_id = "research-"+str(time.time_ns())
    request = "Fai una ricerca sulle prove di un oceano sotto Europa e sugli obiettivi di Europa Clipper. Consegna un PDF con fonti."
    repository.create_task(task_id,"research",request)
    context = TaskContext(task_id,threading.Event(),180,origin="chat")
    approvals = []
    artifacts = []
    def approve(request,ctx):
        assert request.call.name=="run_research"
        approvals.append(request.call.name)
        return registry.policy.approvals.issue(request)
    def emit(event):
        if event.kind=="autonomy" and event.data.get("stage"):
            print(event.data["stage"],flush=True)
        if event.kind=="artifact":
            artifacts.append(event.data)
    report = {"passed":False,"external_account_writes":False,"chatgpt_live_verified":False,"google_docs_live_verified":False}
    started = time.monotonic()
    try:
        plan = OllamaProvider(settings.ollama).plan_research(request,context)
        assert not plan["use_chatgpt"] and not plan["use_google_docs"]
        report["plan"] = plan
        controller.execute_tool(ToolCall("run_research",json.dumps(plan)),context,emit,approve)
        message = ResearchExecutor(controller,services).run(plan,context,emit,approve)
        assert len(artifacts)==1 and artifacts[0]["verified"]
        state = json.loads((Path(artifacts[0]["path"]).parent/"stato.json").read_text(encoding="utf-8"))
        assert state["status"]=="completed" and len(state["sources"])>=2
        report.update(passed=True,real_qwen=True,real_public_sources=True,real_pdf=True,artifact=artifacts[0],
                      source_urls=[s["url"] for s in state["sources"]],search_engines=[s["engine"] for s in state["searches"]],
                      initial_approvals=len(approvals),message=message)
    except Exception as exc:
        report["error"] = type(exc).__name__+": "+str(exc)
        raise
    finally:
        services.searcher.google.browser.transport.close()
        report["seconds"] = round(time.monotonic()-started,2)
        (folder/"research.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(report,ensure_ascii=False),flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
