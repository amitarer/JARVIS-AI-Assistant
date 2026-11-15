"""Create only a new owned Google document; verify by exporting its actual text."""

from pathlib import Path
import re
import secrets
import time
from urllib.parse import quote

from jarvis.browser.controller import BrowserController
from jarvis.core.models import UserError
from jarvis.research.report import validate_pdf


READY_JS = r'''(() => {
 const frame=document.querySelector('iframe.docs-texteventtarget-iframe');
 const title=document.querySelector('input.docs-title-input');
 return {ready:!!(frame&&frame.contentDocument&&title),title:title?title.value:'',url:location.href};
})()'''


class GoogleDocuments:
    def __init__(self, root):
        self.browser = BrowserController(root, allowed_origin="https://docs.google.com")
        self.document_id = None
        self.written = False
        self.browser.allowed_path = None

    def open_new(self, context):
        self.document_id = None
        self.written = False
        self.browser.allowed_path = None
        self.browser.open_chat(context,url="https://docs.google.com/document/u/0/create")
        return {"opened":True,"service":"Google Documenti","requires_new_document":True}

    def ready(self, context):
        try:
            state = self.browser._evaluate(READY_JS, context)
        except UserError:
            return False
        match = re.search(r"/document/d/([A-Za-z0-9_-]+)/",state.get("url", ""))
        if state.get("ready") and match:
            if self.document_id and self.document_id != match.group(1):
                raise UserError("Il documento selezionato e' cambiato. Scrittura interrotta.")
            if not self.document_id and state.get("title", "").strip().casefold() not in {"untitled document","documento senza titolo"}:
                raise UserError("La scheda non contiene un nuovo documento senza titolo. Nessun documento esistente verra' modificato.")
            self.document_id = match.group(1)
            self.browser.allowed_path = f"/document/d/{self.document_id}/"
            return True
        return False

    def _key(self, key, code, context, *, modifiers=0):
        for kind in ("keyDown","keyUp"):
            self.browser._call("Input.dispatchKeyEvent",{"type":kind,"key":key,"windowsVirtualKeyCode":code,"modifiers":modifiers},context)

    def write_and_export(self, title, text, folder, context):
        if not self.document_id or not self.ready(context):
            raise UserError("Il nuovo documento Google non e' pronto. Completa l'accesso nel browser dedicato.")
        folder = Path(folder).resolve()
        if not folder.is_relative_to(self.browser.root / "data/reports"):
            raise UserError("Cartella di esportazione non autorizzata.")
        if self.written:
            raise UserError("Il testo e' gia' stato inserito: non viene ripetuto dopo un esito incerto.")
        download = folder / "google-downloads"
        download.mkdir(exist_ok=True)
        if download.is_symlink() or download.is_junction() or not download.resolve().is_relative_to(folder):
            raise UserError("Cartella download non valida.")
        existing = self._download("txt",download,context).read_text(encoding="utf-8-sig",errors="replace")
        if existing.strip():
            raise UserError("Il documento Google contiene gia' del testo. Scrittura interrotta per conservarlo.")
        self.ready(context)
        focus_title = "(() => {const e=document.querySelector('input.docs-title-input');if(!e)return false;e.focus();e.select();return true;})()"
        if not self.browser._evaluate(focus_title,context):
            raise UserError("Titolo del nuovo documento non disponibile.")
        self.browser._call("Input.insertText",{"text":title},context)
        self._key("Enter",13,context)
        focus_body = "(() => {const f=document.querySelector('iframe.docs-texteventtarget-iframe');if(!f||!f.contentDocument)return false;const e=f.contentDocument.querySelector('[contenteditable=true],textarea')||f.contentDocument.body;e.focus();return true;})()"
        if not self.browser._evaluate(focus_body,context):
            raise UserError("Campo di modifica Google Documenti non accessibile.")
        self.written = True
        self.browser._call("Input.insertText",{"text":text},context)
        # Verify the actual saved content before claiming success or exporting PDF.
        normalize = lambda value: " ".join(value.split())
        verified = False
        for _ in range(3):
            exported = self._download("txt",download,context)
            actual = exported.read_text(encoding="utf-8-sig",errors="replace")
            if normalize(text) == normalize(actual):
                verified = True
                break
            context.cancellation.wait(2)
        if not verified:
            raise UserError("Google Documenti non ha confermato tutto il testo. Nessun PDF dichiarato completato; controlla il nuovo documento.")
        pdf = self._download("pdf",download,context)
        destination = folder / "ricerca.pdf"
        destination.write_bytes(pdf.read_bytes())
        verified = validate_pdf(destination,expected_title=title)
        return {**verified,"document_url":f"https://docs.google.com/document/d/{self.document_id}/edit",
                "google_docs_verified":True,"text_export_verified":True}

    def _download(self, extension, folder, context):
        context.checkpoint()
        if extension not in {"txt","pdf"}:
            raise UserError("Formato di esportazione non previsto.")
        # Chrome may overwrite a same-named export. A fresh directory identifies this request.
        folder = folder/(extension+"-"+secrets.token_hex(4))
        folder.mkdir()
        self.browser._call("Browser.setDownloadBehavior",{"behavior":"allow","downloadPath":str(folder)},context)
        url = f"{self.browser.origin}/document/d/{self.document_id}/export?format={extension}"
        self.browser._http("/json/new?" + quote(url,safe=""),context,"PUT")
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            context.checkpoint()
            candidates = [path for path in folder.iterdir() if path.suffix.casefold() == "."+extension and path.is_file()]
            if candidates and not any(path.suffix == ".crdownload" for path in folder.iterdir()):
                return candidates[0]
            context.cancellation.wait(0.2)
        raise UserError("Esportazione Google Documenti non completata. Verifica accesso, salvataggio e download nella finestra dedicata.")
