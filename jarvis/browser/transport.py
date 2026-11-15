"""Persistent, cancellable CDP channel using Windows components already installed."""

import atexit
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
from urllib.parse import urlsplit

from jarvis.core.models import UserError


class BrowserTransport:
    def __init__(self):
        self.process = None
        self.responses = None
        self.lock = threading.Lock()
        self.sequence = 0
        atexit.register(self.close)

    def _start(self):
        if self.process and self.process.poll() is None:
            return
        executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        self.process = subprocess.Popen([str(executable), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(Path(__file__).with_name("transport.ps1"))], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW, bufsize=1)
        responses = self.responses = queue.Queue()
        process = self.process
        def read():
            try:
                for line in process.stdout:
                    if len(line) <= 24000000:
                        responses.put(line)
                    else:
                        responses.put(None)
            finally:
                responses.put(None)
        threading.Thread(target=read, name="browser-responses", daemon=True).start()

    def call(self, endpoint, method, parameters, context):
        parsed = urlsplit(endpoint)
        if parsed.scheme != "ws" or parsed.hostname != "127.0.0.1":
            raise UserError("Endpoint browser non autorizzato.")
        while not self.lock.acquire(timeout=0.05):
            context.checkpoint()
        try:
            context.checkpoint()
            self._start()
            self.sequence += 1
            request_id = self.sequence
            packet = {"id":request_id,"endpoint":endpoint,"method":method,"params":parameters,
                      "timeout_ms":max(100, min(15000, int(context.remaining * 1000)))}
            self.process.stdin.write(json.dumps(packet, ensure_ascii=True) + "\n")
            self.process.stdin.flush()
            while True:
                context.checkpoint()
                try:
                    line = self.responses.get(timeout=0.05)
                except queue.Empty:
                    continue
                if line is None:
                    raise UserError("Collegamento browser interrotto.")
                try:
                    response = json.loads(line)
                except ValueError:
                    raise UserError("Risposta browser non valida.") from None
                if response.get("id") != request_id:
                    continue
                if "error" in response:
                    raise UserError("Il browser non ha confermato l'operazione.")
                return response["result"]
        except BaseException:
            self.close()
            raise
        finally:
            self.lock.release()

    def close(self):
        process, self.process = self.process, None
        if process:
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
            for stream in (process.stdin, process.stdout):
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
