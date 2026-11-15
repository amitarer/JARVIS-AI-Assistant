"""Real Chrome + Qwen session against a local fixture; no external messages sent."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import nullcontext
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.browser.controller import BrowserController
from jarvis.core.controller import Controller
from jarvis.core.models import Cancelled, ToolCall
from jarvis.core.task_executor import TaskExecutor
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import load_settings
from jarvis.memory.database import Database
from jarvis.memory.repository import Repository
from jarvis.security.approvals import ApprovalStore
from jarvis.security.policy import SecurityPolicy
from jarvis.tools.autonomy import BrowserChatTool, StartAutonomousChatTool
from jarvis.tools.registry import ToolRegistry

PAGE = b'''<!doctype html><html><head><title>JARVIS local conversation test</title></head>
<body><main><div id="messages"></div><textarea id="prompt-textarea"></textarea>
<button data-testid="send-button" disabled>Invia</button><button data-testid="stop-button" hidden>Stop generating</button>
</main><script>
const input=document.querySelector('textarea'), send=document.querySelector('[data-testid="send-button"]');
const stop=document.querySelector('[data-testid="stop-button"]'), messages=document.querySelector('#messages');
let turns=0;
input.addEventListener('input',()=>send.disabled=!input.value.trim());
send.addEventListener('click',()=>{
 const text=input.value; if(!text.trim())return;
 const user=document.createElement('div');user.dataset.messageAuthorRole='user';user.textContent=text;messages.append(user);
 fetch('/message',{method:'POST',body:JSON.stringify({text})});input.value='';send.disabled=true;stop.hidden=false;
 setTimeout(()=>{const assistant=document.createElement('div');assistant.dataset.messageAuthorRole='assistant';
 assistant.textContent='Risposta di prova '+(++turns)+': grazie, continua con una domanda diversa.';messages.append(assistant);stop.hidden=true;},120);
});
</script></body></html>'''


def main():
    posted = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)
        def do_POST(self):
            posted.append(json.loads(self.rfile.read(min(10000, int(self.headers.get("Content-Length", 0))))))
            self.send_response(204)
            self.end_headers()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    folder = ROOT / "data/verification"
    folder.mkdir(parents=True, exist_ok=True)
    base = ROOT / "data/test-runs"
    base.mkdir(parents=True, exist_ok=True)
    report = {"external_messages_sent": False, "passed": False}
    browser = None
    try:
        # Chrome creates protected cache directories on Windows: retain this isolated run for review.
        with nullcontext(tempfile.mkdtemp(prefix="autonomy-", dir=base)) as directory:
            root = Path(directory).resolve()
            assert root.is_relative_to(base.resolve())
            report["test_directory"] = str(root)
            database = Database(root / "data/session.sqlite3")
            database.initialize()
            repository = Repository(database)
            registry = ToolRegistry(SecurityPolicy(ApprovalStore()))
            browser = BrowserController(root, allowed_origin=f"http://127.0.0.1:{server.server_port}", headless=True)
            for operation in ("open", "observe", "send", "reply"):
                registry.register(BrowserChatTool(browser, operation))
            registry.register(StartAutonomousChatTool())
            controller = Controller(load_settings(ROOT), repository, registry)
            repository.create_task("autonomy-native-test", "autonomous", "Conversazione locale fino a STOP")
            cancellation = threading.Event()
            parent = TaskContext("autonomy-native-test", cancellation, 180, origin="chat")
            approvals = []
            def approve(request, context):
                assert request.call.name == "start_autonomous_chat", request.call.name
                approvals.append(request.call.name)
                return registry.policy.approvals.issue(request)
            registry.execute(ToolCall("start_autonomous_chat", '{"objective":"Fai domande brevi e diverse su astronomia e scienza, in italiano."}'), parent, approve)
            events = []
            failures = [0]
            def emit(event):
                events.append(event)
                if event.kind == "autonomy":
                    print(json.dumps({"stage": event.data.get("stage"), "turns": event.data.get("turns")}), flush=True)
                    if "In attesa:" in event.data.get("stage", ""):
                        failures[0] += 1
                        if failures[0] >= 2:
                            cancellation.set()
                if event.kind == "autonomy" and event.data.get("last_reply") and event.data["turns"] >= 3:
                    cancellation.set()
            started = time.monotonic()
            stopped = False
            watchdog = threading.Timer(100, cancellation.set)
            watchdog.start()
            try:
                TaskExecutor(controller).run_chat("Fai domande brevi e diverse su astronomia e scienza, in italiano.", parent, emit, approve)
            except Cancelled:
                stopped = True
            finally:
                watchdog.cancel()
            operations = repository.operations(limit=50)
            verified = [row for row in operations if row["tool"] == "browser_chat_send" and row["status"] == "succeeded"]
            replies = [row for row in operations if row["tool"] == "browser_chat_reply" and row["status"] == "succeeded"]
            count_at_stop = len(posted)
            time.sleep(0.3)
            report.update(real_chrome=True, real_qwen=any(event.kind == "usage" and event.data.get("provider") == "ollama" for event in events), posted_messages=len(posted), verified_sends=len(verified),
                          verified_replies=len(replies), initial_approvals=len(approvals), stopped=stopped,
                          no_sends_after_stop=len(posted) == count_at_stop, seconds=round(time.monotonic()-started, 2))
            report["passed"] = (stopped and len(posted) == 3 and len(verified) == 3 and len(replies) == 3
                                and len(approvals) == 1 and report["no_sends_after_stop"])
            browser.close(TaskContext("close-test-browser", threading.Event(), 10))
            time.sleep(0.3)
            browser = None
    finally:
        if browser and browser.process and browser.process.poll() is None:
            subprocess.run(["taskkill.exe", "/PID", str(browser.process.pid), "/T", "/F"], capture_output=True)
        server.shutdown()
        (folder / "autonomous-chat.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
