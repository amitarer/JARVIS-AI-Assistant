"""Verify real idle capture with tray mode, no wake simulation or Windows actions."""

import json
from pathlib import Path
import secrets
import sys
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
from jarvis.ui.background import BackgroundDesktop


def main():
    app = QApplication([])
    settings = load_settings(ROOT)
    database = Database(ROOT / ("data/verification/background-" + secrets.token_hex(3) + ".sqlite3"))
    database.initialize()
    controller = Controller(settings, Repository(database), ToolRegistry(SecurityPolicy(ApprovalStore())))
    window = MainWindow()
    presenter = Presenter(window, controller)
    presenter.probe_needed = False
    desktop = BackgroundDesktop(presenter)
    evidence = {"tray_available": desktop.available, "real_microphone_samples": 0,
                "main_window_hidden": False, "overlay_hidden_without_wake": False}
    presenter.voice.audio.frames.connect(lambda samples: evidence.update(real_microphone_samples=evidence["real_microphone_samples"] + len(samples)))
    presenter.voice.error.connect(lambda message: evidence.update(error=message))
    desktop.start(dashboard=False, auto_listen=True)
    timer = QTimer()
    timer.setInterval(100)
    started = time.monotonic()

    def inspect():
        if presenter.voice.enabled and evidence["real_microphone_samples"] >= 12000:
            evidence["main_window_hidden"] = not window.isVisible()
            evidence["overlay_hidden_without_wake"] = not presenter.overlay.isVisible()
            evidence["phase"] = presenter.voice.phase
            evidence["global_stop_registered"] = bool(desktop.hotkey and desktop.hotkey.registered)
            desktop.show_dashboard()
            window.close()
            evidence["dashboard_close_keeps_listening"] = presenter.voice.enabled and not window.isVisible() and not presenter.closing
            evidence["passed"] = all((evidence["tray_available"], evidence["main_window_hidden"],
                                        evidence["overlay_hidden_without_wake"], evidence["dashboard_close_keeps_listening"],
                                        evidence["phase"] == "wake"))
            timer.stop()
            desktop.quit()
        elif time.monotonic() - started > 15:
            evidence["passed"] = False
            evidence["notice"] = window.microphone_label.text()
            timer.stop()
            desktop.quit()

    timer.timeout.connect(inspect)
    timer.start()
    app.exec()
    evidence["microphone_closed_on_exit"] = not presenter.voice.audio.enabled
    evidence["hotkey_released_on_exit"] = not desktop.hotkey or not desktop.hotkey.registered
    path = ROOT / "data/verification/background-mode.json"
    path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=True))
    return 0 if evidence.get("passed") and evidence["microphone_closed_on_exit"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
