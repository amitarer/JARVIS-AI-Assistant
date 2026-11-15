"""Native UI → live Qwen → final-only TTS check. Microphone stays off; audio muted."""

import json
from pathlib import Path
import secrets
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from jarvis.core.controller import Controller
from jarvis.infrastructure.settings import load_settings
from jarvis.memory.database import Database
from jarvis.memory.repository import Repository
from jarvis.security.approvals import ApprovalStore
from jarvis.security.policy import SecurityPolicy
from jarvis.tools.registry import ToolRegistry
from jarvis.ui.main_window import MainWindow
from jarvis.ui.presenter import Presenter


def main():
    app = QApplication([])
    app.setStyleSheet((ROOT / "jarvis/ui/theme.qss").read_text(encoding="utf-8"))
    settings = load_settings(ROOT)
    nonce = "QWEN-" + secrets.token_hex(3).upper()
    folder = ROOT / "data/verification"
    folder.mkdir(exist_ok=True)
    database = Database(folder / (nonce + "-ui.sqlite3"))
    database.initialize()
    controller = Controller(settings, Repository(database), ToolRegistry(SecurityPolicy(ApprovalStore())))
    window = MainWindow()
    presenter = Presenter(window, controller)
    presenter.probe_needed = False
    presenter.speech.volume = 0
    evidence = {"model": settings.ollama.model, "microphone_enabled": False, "muted_playback": True,
                "stream_chunks": 0, "tts_inputs": [], "pcm_bytes": 0, "errors": []}
    original_speak = presenter.speech.speak

    def speak(text):
        evidence["tts_inputs"].append(text)
        return original_speak(text)

    presenter.speech.speak = speak
    presenter.speech.error.connect(evidence["errors"].append)
    presenter.speech.pcm_ready.connect(lambda data, fmt: evidence.update(pcm_bytes=len(data)))
    window.show()
    presenter.start({"kind": "voice", "text": f"Rispondi esattamente: Buongiorno Gae. Codice di verifica {nonce}."})
    presenter.worker.event.connect(lambda event: evidence.update(stream_chunks=evidence["stream_chunks"] + 1) if event.kind == "stream" else None)
    timer = QTimer()
    timer.setInterval(50)
    started = time.monotonic()

    def inspect():
        if presenter.worker is None and evidence["pcm_bytes"] and presenter.speech.played_microseconds > 100000:
            evidence["final_response"] = presenter.last_response
            evidence["stop_available_during_tts"] = window.stop_button.isEnabled()
            window.grab().save(str(folder / "qwen-ui.png"))
            presenter.stop()
            evidence["stop_released_audio"] = presenter.speech.sink is None
            evidence["microphone_enabled"] = presenter.voice.enabled
            evidence["passed"] = (nonce in presenter.last_response and evidence["tts_inputs"] == [presenter.last_response]
                                    and evidence["stream_chunks"] > 1 and not evidence["errors"]
                                    and evidence["stop_available_during_tts"] and evidence["stop_released_audio"])
            presenter.close()
            timer.stop()
        elif time.monotonic() - started > 60:
            evidence["passed"] = False
            evidence["notice"] = window.action_label.text()
            presenter.close()
            timer.stop()

    timer.timeout.connect(inspect)
    timer.start()
    app.exec()
    (folder / "qwen-ui-verification.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=True))
    return 0 if evidence.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
