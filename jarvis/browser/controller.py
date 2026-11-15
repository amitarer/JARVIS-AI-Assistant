"""Structured Chrome control in a dedicated profile using existing Windows APIs."""

import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import quote, urlsplit
from urllib.request import build_opener, ProxyHandler, Request

from jarvis.core.models import UserError
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.windows import powershell
from jarvis.browser.transport import BrowserTransport


class BrowserController:
    def __init__(self, root, *, allowed_origin="https://chatgpt.com", profile_name="browser-profile", headless=False):
        self.root = root.resolve()
        self.origin = allowed_origin.rstrip("/")
        parsed = urlsplit(self.origin)
        if self.origin not in {"https://chatgpt.com", "https://www.google.com", "https://docs.google.com"} and not (parsed.scheme == "http" and parsed.hostname == "127.0.0.1"):
            raise ValueError("Origine browser non autorizzata.")
        self.profile = self.root / "data" / profile_name
        if self.profile.is_symlink() or self.profile.is_junction() or not self.profile.resolve().is_relative_to(self.root / "data"):
            raise UserError("Il profilo browser deve rimanere nella cartella dati del progetto.")
        self.headless = headless
        self.port = None
        self.target_id = None
        self.allowed_path = None
        self.process = None
        self.opener = build_opener(ProxyHandler({}))
        self.transport = BrowserTransport()

    def _http(self, path, context, method="GET"):
        context.checkpoint()
        request = Request(f"http://127.0.0.1:{self.port}" + path, method=method)
        try:
            with self.opener.open(request, timeout=min(2, context.remaining)) as response:
                raw = response.read(1000001)
            if len(raw) > 1000000:
                raise ValueError
            return json.loads(raw)
        except (OSError, ValueError):
            context.checkpoint()
            raise UserError("Browser dedicato non raggiungibile. Controlla la sua finestra.") from None

    def _chrome_executable(self):
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for access in (winreg.KEY_READ | winreg.KEY_WOW64_64KEY, winreg.KEY_READ | winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe", 0, access) as key:
                        candidate = Path(winreg.QueryValueEx(key, "")[0].strip('"'))
                        if candidate.is_file():
                            return candidate
                except OSError:
                    pass
        candidates = [(os.environ.get("ProgramFiles"), "Google/Chrome/Application/chrome.exe"),
                      (os.environ.get("LOCALAPPDATA"), "Google/Chrome/Application/chrome.exe")]
        for base, relative in candidates:
            if base and (Path(base) / relative).is_file():
                return Path(base) / relative
        raise UserError("Google Chrome non trovato. Il browser dedicato richiede Chrome installato.")

    def _existing(self, context):
        try:
            lines = (self.profile / "DevToolsActivePort").read_text().splitlines()
            port = int(lines[0])
            if not 1 <= port <= 65535 or not lines[1].startswith("/devtools/browser/"):
                return False
            self.port = port
            version = self._http("/json/version", context)
            return version.get("webSocketDebuggerUrl") == f"ws://127.0.0.1:{port}{lines[1]}"
        except (OSError, ValueError, IndexError, UserError):
            self.port = None
            return False

    def open_chat(self, context, *, url=None):
        url = url or self.origin + "/"
        parsed = urlsplit(url)
        if f"{parsed.scheme}://{parsed.netloc}" != self.origin:
            raise UserError("Destinazione browser fuori dall'origine autorizzata.")
        if not self._existing(context):
            self.profile.mkdir(parents=True, exist_ok=True)
            (self.profile / "DevToolsActivePort").unlink(missing_ok=True)
            args = [str(self._chrome_executable()), "--user-data-dir=" + str(self.profile),
                    "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
                    "--no-first-run", "--no-default-browser-check"]
            if self.headless:
                args.extend(["--headless=new", "--disable-gpu"])
            args.append("about:blank")
            context.checkpoint()
            self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                context.checkpoint()
                if self._existing(context):
                    break
                context.cancellation.wait(0.1)
            else:
                raise UserError("Chrome non ha aperto il profilo dedicato entro 15 secondi.")
        target = self._http("/json/new?" + quote(url, safe=""), context, "PUT")
        self.target_id = target["id"]
        return {"target_id": self.target_id, "url": url, "profile": "JARVIS dedicato", "opened": True}

    def navigate(self, url, context):
        parsed = urlsplit(url)
        if f"{parsed.scheme}://{parsed.netloc}" != self.origin:
            raise UserError("Navigazione fuori dall'origine autorizzata.")
        return self._call("Page.navigate", {"url":url}, context)

    def _target(self, context):
        if not self.target_id:
            raise UserError("Nessuna conversazione browser aperta per questa sessione.")
        target = next((item for item in self._http("/json/list", context) if item.get("id") == self.target_id), None)
        if not target:
            raise UserError("La scheda della conversazione e' stata chiusa.")
        parsed = urlsplit(target.get("url", ""))
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin != self.origin:
            raise UserError("La scheda richiede accesso o navigazione fuori dalla conversazione autorizzata. Intervieni nel browser.")
        if self.allowed_path and not parsed.path.startswith(self.allowed_path):
            raise UserError("La scheda non contiene il documento autorizzato. Scrittura interrotta.")
        return target

    def _call(self, method, parameters, context):
        target = self._target(context)
        endpoint = target["webSocketDebuggerUrl"]
        return self._transport(endpoint, method, parameters, context)

    def _transport(self, endpoint, method, parameters, context):
        parsed = urlsplit(endpoint)
        if parsed.scheme != "ws" or parsed.hostname != "127.0.0.1" or parsed.port != self.port:
            raise UserError("Endpoint della scheda non autorizzato.")
        child = TaskContext(context.task_id, context.cancellation, min(15, context.remaining), origin=context.origin)
        return self.transport.call(endpoint, method, parameters, child)

    def close(self, context):
        """Close only this dedicated browser instance; used by owned test fixtures."""
        version = self._http("/json/version", context)
        try:
            self._transport(version["webSocketDebuggerUrl"], "Browser.close", {}, context)
        except UserError:
            pass  # Chrome can close the socket before its final acknowledgement.
        if self.process:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        self.transport.close()

    def _evaluate(self, expression, context):
        result = self._call("Runtime.evaluate", {"expression": expression, "returnByValue": True}, context)
        if result.get("exceptionDetails"):
            raise UserError("L'interfaccia della pagina non e' compatibile con il comando richiesto.")
        return result.get("result", {}).get("value")

    def observe(self, context):
        result = self._evaluate(Path(__file__).with_name("chat_page.js").read_text(encoding="utf-8"), context)
        if not isinstance(result, dict):
            raise UserError("La pagina non ha restituito uno stato leggibile.")
        return result

    def send(self, text, context):
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1800 or "\x00" in text:
            raise UserError("Messaggio browser non valido.")
        before = self.observe(context)
        if before["challenge"] or before["login_required"] or not before["composer_ready"] or before["busy"]:
            raise UserError("ChatGPT non e' pronto: completa accesso o verifica nella finestra dedicata.")
        if before["draft"].strip():
            raise UserError("C'e' una bozza nel campo messaggio. Non viene sovrascritta automaticamente.")
        focus = "(() => {const e=document.querySelector('#prompt-textarea,textarea[data-testid=\"prompt-textarea\"],main [contenteditable=\"true\"],main textarea'); if(!e)return false;e.focus();return true;})()"
        if not self._evaluate(focus, context):
            raise UserError("Campo messaggio non disponibile.")
        context.checkpoint()
        self._call("Input.insertText", {"text": text}, context)
        state = self.observe(context)
        if state["draft"].strip() != text.strip() or not state["send"] or not state["send"]["enabled"]:
            raise UserError("Il testo o il pulsante di invio non corrisponde: messaggio non inviato.")
        button = state["send"]
        context.checkpoint()
        for kind in ("mousePressed", "mouseReleased"):
            self._call("Input.dispatchMouseEvent", {"type": kind, "x": button["x"], "y": button["y"], "button": "left", "clickCount": 1}, context)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = self.observe(context)
            if state["user_count"] > before["user_count"] and state["last_user"].strip() == text.strip():
                return {"submitted": True, "verification": "user_message_in_dom", "user_count": state["user_count"], "assistant_baseline": before["assistant_count"], "url": state["url"]}
            context.cancellation.wait(0.15)
        raise UserError("Invio non verificato. La sessione non ripete il clic per evitare messaggi duplicati.")

    def wait_reply(self, baseline, context):
        last, stable_since = "", time.monotonic()
        while True:
            context.checkpoint()
            state = self.observe(context)
            text = state["last_reply"]
            if text != last:
                last, stable_since = text, time.monotonic()
            if text and state["assistant_count"] > baseline and not state["busy"] and time.monotonic() - stable_since >= 1:
                return {"reply": text, "assistant_count": state["assistant_count"], "reply_verified": True,
                        "verification": "assistant_message_stable_not_busy", "url": state["url"]}
            context.cancellation.wait(0.3)
