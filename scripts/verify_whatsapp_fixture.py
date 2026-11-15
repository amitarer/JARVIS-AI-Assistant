"""Real Chrome/CDP against a local WhatsApp-shaped LAB fixture, never an account."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import replace
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import threading
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.browser.controller import BrowserController
from jarvis.browser.whatsapp import WhatsAppBrowser
from jarvis.core.models import ToolCall, UserError
from jarvis.core.tasks import TaskContext
from jarvis.security.approvals import ApprovalStore
from jarvis.security.policy import SecurityPolicy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.whatsapp import WhatsAppMessageTool
from jarvis.bootstrap import build_tool_registry
from jarvis.infrastructure.settings import load_settings
from tests.support import make_controller

HTML = b'''<!doctype html><html><head><meta charset="utf-8"></head><body>
<h1>LOCAL LAB FIXTURE - NOT WHATSAPP</h1>
<aside id="side"><div contenteditable="true" role="textbox" style="width:300px;height:35px;border:1px solid">Search</div></aside>
<div id="pane-side"><div role="row" style="height:45px;width:300px;background:#ddd"><span title="Paolo">Paolo</span></div></div>
<section id="main"><header><span title="Other">Other</span></header><div id="messages"></div>
<footer><div contenteditable="true" role="textbox" style="height:60px;width:400px;border:1px solid"></div>
<button><span data-icon="send">Send</span></button></footer></section>
<script>
document.querySelector('[role=row]').onclick=()=>{const h=document.querySelector('header span');h.title='Paolo';h.textContent='Paolo';};
document.querySelector('button').onclick=()=>{const e=document.querySelector('footer [contenteditable]');
 const r=document.createElement('div');r.className='message-out';const s=document.createElement('span');s.className='selectable-text';
 s.textContent=e.innerText.trim();r.append(s);document.querySelector('#messages').append(r);e.textContent='';};
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML)

    def log_message(self, *_):
        pass


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    context = TaskContext("whatsapp-local-fixture", threading.Event(), 60)
    report = {"fixture": "local_lab_not_whatsapp", "real_chrome_cdp": True, "external_messages_sent": 0}
    base=ROOT/"data/test-runs"
    base.mkdir(parents=True,exist_ok=True)
    # Retain LAB evidence: Windows can protect Chrome cache files even after exit.
    # The owned browser is still explicitly closed; no user profile is cleaned.
    with nullcontext(tempfile.mkdtemp(prefix="whatsapp-lab-",dir=base)) as directory:
        assert Path(directory).resolve().is_relative_to(base.resolve())
        report["fixture_artifacts"]=str(Path(directory).relative_to(ROOT))
        browser = BrowserController(Path(directory), allowed_origin=f"http://127.0.0.1:{server.server_port}",
                                    profile_name="whatsapp-fixture", headless=True)
        service = WhatsAppBrowser(Path(directory), browser)
        registry = ToolRegistry(SecurityPolicy(ApprovalStore()))
        registry.register(WhatsAppMessageTool(service))
        registry.register(WhatsAppMessageTool(service, send=True))
        def approve(request, ctx):
            return registry.policy.approvals.issue(request)
        try:
            draft = registry.execute(ToolCall("prepare_whatsapp_message", '{"recipient":"Paolo","text":"Arrivo tra dieci minuti."}'), context, approve)
            assert draft.evidence["draft_verified"] and draft.evidence["sent"] is False
            before = service.observe(context, "Arrivo tra dieci minuti.")
            assert before["matching_outgoing"] == 0
            call = ToolCall("send_whatsapp_message", '{"recipient":"Paolo","text":"Arrivo tra dieci minuti."}')
            denied = False
            try:
                registry.execute(call, context, lambda *_: None)
            except UserError:
                denied = True
            assert denied and service.observe(context, "Arrivo tra dieci minuti.")["matching_outgoing"] == 0
            sent = registry.execute(call, context, approve)
            assert sent.evidence["message_visible"] is True and sent.evidence["delivery_verified"] is False
            repeated = False
            try:
                registry.execute(call, context, approve)
            except UserError:
                repeated = True
            assert repeated
            report.update(passed=True, draft_verified=True, denied_send_blocked=True,
                          lab_dom_message_verified=True, replay_blocked=True)
            controller = make_controller(Path(directory))
            controller.settings = replace(controller.settings, ollama=load_settings(ROOT).ollama)
            controller.tools = build_tool_registry(controller.settings, controller.repository)
            for name in ("prepare_whatsapp_message", "send_whatsapp_message"):
                controller.tools._tools[name].service = service
            execute = controller.execute_tool
            calls = []
            expected = "Prova locale del coordinatore."
            def only_lab_messages(call, *args, **kwargs):
                print(json.dumps({"lab_tool": call.name, "lab_arguments": json.loads(call.arguments_json)}), flush=True)
                assert call.name in {"prepare_whatsapp_message", "send_whatsapp_message"}, call.name
                assert json.loads(call.arguments_json) == {"recipient": "Paolo", "text": expected}
                calls.append(call.name)
                return execute(call, *args, **kwargs)
            controller.execute_tool = only_lab_messages
            for sending in (False, True):
                request = (("Invia" if sending else "Prepara solo una bozza, senza inviare,") +
                           " su WhatsApp a Paolo il testo esatto tra virgolette: " + json.dumps(expected))
                controller.run({"kind": "chat", "text": request}, threading.Event(), lambda *_: None,
                               lambda proposal, ctx: controller.tools.policy.approvals.issue(proposal))
                task = controller.repository.tasks()[0]
                assert task["status"] == "succeeded", task["error_text"]
                state = service.observe(context, expected)
                assert state["matching_outgoing"] == (1 if sending else 0), state
            report.update(real_local_qwen=True, model_selected_tools=calls,
                          model_draft_did_not_send=True, model_send_verified_in_lab=True)
        finally:
            if browser.port:
                browser.close(TaskContext("close-owned-fixture", threading.Event(), 10))
            server.shutdown()
    destination = ROOT / "data/verification/whatsapp-fixture.json"
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
