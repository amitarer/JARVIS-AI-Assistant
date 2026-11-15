"""Real Chrome typing/download round trip against a local Docs-shaped fixture only."""

from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import html
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from jarvis.browser.controller import BrowserController
from jarvis.core.tasks import TaskContext
from jarvis.research.google_docs import GoogleDocuments
from jarvis.research.report import export_pdf


def main():
    app=QApplication.instance() or QApplication([])
    for font in ("segoeui.ttf","segoeuib.ttf"):
        QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts")/font))
    base=ROOT/"data/test-runs"
    base.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix="docs-fixture-",dir=base))
    folder=root/"data/reports/test"
    folder.mkdir(parents=True)
    state={"title":"Untitled document","text":""}
    frame="<body contenteditable='true'><script>document.body.addEventListener('input',()=>parent.save())</script></body>"
    page=("<input class='docs-title-input' value='Untitled document' oninput='save()'>"
          "<iframe class='docs-texteventtarget-iframe' srcdoc=\""+html.escape(frame,quote=True)+"\"></iframe>"
          "<script>function save(){fetch('/save',{method:'POST',body:JSON.stringify({title:document.querySelector('input').value,"
          "text:document.querySelector('iframe').contentDocument.body.innerText})})}</script>").encode()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            state.update(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(204);self.end_headers()
        def do_GET(self):
            if "format=txt" in self.path:
                content=state["text"].encode();kind="text/plain";name="report.txt"
            elif "format=pdf" in self.path:
                report={"title":state["title"],"summary":state["text"],"sections":[{"heading":"Contenuto salvato","paragraphs":["Test locale"],"source_ids":[1]}],"limitations":[]}
                sources=[{"id":1,"title":"Fixture locale","url":"https://example.org","retrieved_at_utc":"2026-11-14"}]
                export_pdf(report,sources,folder,TaskContext("fixture-export",threading.Event(),10))
                content=(folder/"ricerca.pdf").read_bytes();kind="application/pdf";name="report.pdf"
            else:
                content=page;kind="text/html";name=None
            self.send_response(200)
            self.send_header("Content-Type",kind+"; charset=utf-8")
            self.send_header("Content-Length",str(len(content)))
            if name:self.send_header("Content-Disposition",f'attachment; filename="{name}"')
            self.end_headers();self.wfile.write(content)
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    documents=GoogleDocuments(root)
    documents.browser=BrowserController(root,allowed_origin=f"http://127.0.0.1:{server.server_port}",headless=True)
    context=TaskContext("docs-fixture",threading.Event(),90)
    result={"passed":False,"local_fixture_only":True,"google_account_accessed":False,"real_chrome":True}
    try:
        documents.browser.open_chat(context,url=documents.browser.origin+"/document/d/test/edit")
        for _ in range(20):
            if documents.ready(context):break
            context.cancellation.wait(0.2)
        title="Prova documento Unicode"
        text="Ricerca salvata e verificata.\nSeconda riga: citta, energia e sostenibilita."
        artifact=documents.write_and_export(title,text,folder,context)
        assert artifact["verified"] and artifact["google_docs_verified"] and state["text"]==text
        result.update(passed=True,artifact=artifact,title_verified=state["title"]==title,text_verified=True)
    finally:
        documents.browser.close(TaskContext("close-fixture",threading.Event(),10))
        server.shutdown()
        (ROOT/"data/verification/google-docs-fixture.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
        print(json.dumps(result),flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
