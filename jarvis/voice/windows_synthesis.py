"""No-dependency WinRT synthesis through a fixed, project-owned script."""

import base64
import io
import json
import os
from pathlib import Path
import subprocess
import threading
import wave

from PySide6.QtCore import QThread, Signal


class WindowsSynthesis(QThread):
    audio = Signal(bytes, int, int, int)
    error = Signal(str)

    def __init__(self, text: str, voice: str, fallback: bool, parent=None):
        super().__init__(parent)
        self.text, self.voice, self.fallback = text, voice, fallback
        self.cancelled = threading.Event()
        self.process = None

    def cancel(self):
        self.cancelled.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def run(self):
        try:
            script = Path(__file__).resolve().parents[2] / "scripts/synthesize_windows.ps1"
            executable = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            # Only this fixed script is executed. The text and voice are data on stdin.
            self.process = subprocess.Popen([str(executable), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            creationflags=subprocess.CREATE_NO_WINDOW, shell=False)
            if self.cancelled.is_set():
                self.process.terminate()
            request = json.dumps({"text": self.text[:2000], "voice": self.voice, "allow_fallback": self.fallback}).encode('ascii')
            output, error = self.process.communicate(request, timeout=15)
            if self.cancelled.is_set():
                return
            if self.process.returncode != 0:
                raise RuntimeError("Windows speech synthesis failed")
            response = json.loads(output.decode('utf-8-sig'))
            wav = base64.b64decode(response["wav"], validate=True)
            with wave.open(io.BytesIO(wav), 'rb') as audio:
                self.audio.emit(audio.readframes(audio.getnframes()), audio.getframerate(), audio.getnchannels(), audio.getsampwidth())
        except Exception as exc:
            if self.process and self.process.poll() is None:
                self.process.kill()
                self.process.communicate()
            if not self.cancelled.is_set():
                self.error.emit("Sintesi Windows locale non riuscita (" + type(exc).__name__ + ").")
