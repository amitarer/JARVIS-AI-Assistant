"""WhatsApp Web in its own profile, with fixed DOM operations and exact drafts."""

import json
from pathlib import Path
import time
from urllib.parse import urlsplit

from jarvis.browser.controller import BrowserController
from jarvis.core.models import ToolResult, UserError, UserActionRequired


class WhatsAppBrowser:
    def __init__(self, root, browser=None):
        self.browser = browser or BrowserController(root, allowed_origin="https://web.whatsapp.com", profile_name="whatsapp-browser-profile")
        self.drafts = {}

    def connect(self, context):
        self.ensure_open(context)
        state = self.wait(context, lambda s: s["ready"] or s["login_required"])
        if not state["ready"]:
            if not state["login_required"]:
                raise UserActionRequired("WhatsApp Web sta caricando o richiede un intervento nella finestra dedicata. Verifica la pagina e ripeti; nessun messaggio inviato.")
            raise UserActionRequired("WhatsApp Web aperto nel profilo JARVIS. Scansiona il QR con il telefono (Dispositivi collegati), poi scrivi fatto. Nessun messaggio inviato.")
        return ToolResult("WhatsApp e' collegato nel profilo JARVIS. Nessun messaggio inviato.", {"connected": True, "sent": False})

    def ensure_open(self, context):
        if self.browser.target_id:
            self.browser._target(context)
            return
        if self.browser._existing(context):
            for tab in self.browser._http("/json/list", context):
                parsed = urlsplit(tab.get("url", ""))
                if tab.get("type") == "page" and f"{parsed.scheme}://{parsed.netloc}" == self.browser.origin:
                    self.browser.target_id = tab["id"]
                    return
        self.browser.open_chat(context)

    def observe(self, context, expected=""):
        script = Path(__file__).with_name("whatsapp_page.js").read_text(encoding="utf-8")
        value = self.browser._evaluate(script.replace("/*EXPECTED*/", json.dumps(expected, ensure_ascii=True)), context)
        if not isinstance(value, dict):
            raise UserError("WhatsApp Web non ha restituito uno stato verificabile.")
        return value

    def wait(self, context, predicate, expected="", seconds=5):
        deadline = time.monotonic() + min(seconds, context.remaining)
        while True:
            context.checkpoint()
            value = self.observe(context, expected)
            if predicate(value) or time.monotonic() >= deadline:
                return value
            context.cancellation.wait(0.15)

    def replace_field(self, context, field, text):
        # Select only this observed field's contents; never send Enter or use a terminal.
        if field not in {"search", "composer"}:
            raise ValueError("Campo WhatsApp non disponibile.")
        selector = '#side [contenteditable="true"][role="textbox"]' if field == "search" else '#main footer [contenteditable="true"][role="textbox"]'
        focused = self.browser._evaluate("(() => {const a=[...document.querySelectorAll(" + json.dumps(selector) +
            ")].filter(e=>e.getClientRects().length);if(a.length!==1)return false;const e=a[0];e.focus();"
            "const r=document.createRange();r.selectNodeContents(e);const s=getSelection();s.removeAllRanges();s.addRange(r);return true;})()", context)
        if not focused:
            raise UserError("Campo WhatsApp cambiato o non univoco.")
        self.browser._call("Input.insertText", {"text": text}, context)

    def click(self, point, context):
        if not point or point.get("enabled") is not True:
            raise UserError("Controllo WhatsApp non disponibile.")
        for kind in ("mousePressed", "mouseReleased"):
            context.checkpoint()
            self.browser._call("Input.dispatchMouseEvent", {"type": kind, "x": point["x"], "y": point["y"],
                "button": "left", "clickCount": 1}, context)

    def prepare(self, recipient, text, context):
        context.checkpoint()
        self.drafts.clear()
        self.ensure_open(context)
        state = self.wait(context, lambda s: s["ready"] or s["login_required"])
        if not state["ready"]:
            if not state["login_required"]:
                raise UserActionRequired("WhatsApp Web non e' ancora pronto. Controlla caricamento/accesso nella finestra dedicata, poi ripeti la richiesta. Nessun messaggio inviato.")
            raise UserActionRequired("Collega WhatsApp al profilo JARVIS: scansiona il QR nella finestra WhatsApp Web aperta, poi ripeti la richiesta. Nessun messaggio inviato.")
        self.replace_field(context, "search", recipient)
        # The selector is fixed; contact text is compared as data, never executed.
        selection = self.browser._evaluate("(() => {const name=" + json.dumps(recipient) +
            ";const norm=s=>s.normalize('NFKC').trim().toLocaleLowerCase();"
            "const rows=[...document.querySelectorAll('#pane-side [role=\"row\"]')].filter(r=>r.getClientRects().length "
            "&& [...r.querySelectorAll('[title]')].some(e=>norm(e.title)===norm(name)));"
            "if(rows.length!==1)return null;const r=rows[0].getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,enabled:true};})()", context)
        if not selection:
            # WhatsApp filters asynchronously; wait for the DOM once before asking for clarification.
            context.cancellation.wait(0.5)
            context.checkpoint()
            selection = self.browser._evaluate("(() => {const name=" + json.dumps(recipient) +
                ";const rows=[...document.querySelectorAll('#pane-side [role=\"row\"]')].filter(r=>r.getClientRects().length && "
                "[...r.querySelectorAll('[title]')].some(e=>e.title.trim().toLocaleLowerCase()===name.trim().toLocaleLowerCase()));"
                "if(rows.length!==1)return null;const r=rows[0].getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,enabled:true};})()", context)
        if not selection:
            raise UserError("Contatto WhatsApp assente o ambiguo. Indica il nome esatto, senza scegliere tra omonimi automaticamente.")
        self.click(selection, context)
        state = self.wait(context, lambda s: s["recipient"].casefold() == recipient.casefold() and s["composer_ready"])
        if state["recipient"].casefold() != recipient.casefold() or not state["composer_ready"]:
            raise UserError("L'intestazione WhatsApp non conferma il destinatario: nessun messaggio scritto.")
        if state["draft"] and state["draft"] != text:
            raise UserError("Esiste gia' una bozza diversa nella chat: non la sovrascrivo.")
        self.replace_field(context, "composer", text)
        state = self.observe(context, text)
        if state["recipient"].casefold() != recipient.casefold() or state["draft"] != text:
            raise UserError("Destinatario o testo della bozza non verificati: non verra' inviata.")
        self.drafts[context.task_id] = {"recipient": recipient, "text": text, "target_id": self.browser.target_id}
        return ToolResult(f"Bozza WhatsApp verificata per {recipient}: «{text}». Non inviata.",
                          {"draft_verified": True, "recipient_verified": True, "sent": False, "backend": "whatsapp_web"})

    def send(self, recipient, text, context):
        context.checkpoint()
        draft = self.drafts.pop(context.task_id, None)
        if not draft or draft != {"recipient": recipient, "text": text, "target_id": self.browser.target_id}:
            raise UserError("Manca questa esatta bozza verificata nello stesso incarico e nella stessa scheda.")
        before = self.observe(context, text)
        if before["recipient"].casefold() != recipient.casefold() or before["draft"] != text:
            raise UserError("Chat o bozza cambiate dopo l'approvazione. Invio annullato.")
        self.click(before["send"], context)
        after = self.wait(context, lambda s: s["matching_outgoing"] > before["matching_outgoing"] and s["draft"] == "", expected=text)
        verified = (after["recipient"].casefold() == recipient.casefold()
                    and after["matching_outgoing"] > before["matching_outgoing"] and after["draft"] == "")
        return ToolResult((f"WhatsApp mostra il nuovo messaggio nella chat di {recipient}. Consegna non verificata."
                           if verified else "Invio richiesto a WhatsApp; esito non verificato. Non riprovo automaticamente."),
                          {"send_clicked": True, "message_visible": verified, "delivery_verified": False, "retry_allowed": False})
