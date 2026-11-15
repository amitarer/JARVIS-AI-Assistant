r"""Smoke-test the actual entrypoint and capture its native Windows rendering.

Run explicitly: .venv\Scripts\python.exe -B scripts/verify_startup.py
Shows JARVIS briefly, then closes it; it never launches other applications.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox

from jarvis.ui.main_window import MainWindow
from run import main


def verify() -> int:
    app = QApplication([])
    app.setQuitOnLastWindowClosed(True)
    started = time.monotonic()
    evidence = {"entrypoint": False, "snapshot": False, "fonts": "Segoe UI" in QFontDatabase.families()}
    timer = QTimer()
    timer.setInterval(100)

    def inspect():
        for widget in app.topLevelWidgets():
            if isinstance(widget, QMessageBox):
                print("Startup dialog:", widget.text())
                widget.reject()
                app.quit()
                return
            if isinstance(widget, MainWindow) and widget.isVisible() and not widget.busy:
                destination = ROOT / "data/verification/foundation-preview.png"
                destination.parent.mkdir(parents=True, exist_ok=True)
                evidence["entrypoint"] = True
                evidence["snapshot"] = widget.grab().save(str(destination))
                widget.close_to_tray = False
                widget.close()
                QTimer.singleShot(100, app.quit)
                timer.stop()
                return
        if time.monotonic() - started > 10:
            timer.stop()
            app.quit()

    timer.timeout.connect(inspect)
    timer.start()
    result = main(dashboard=True, microphone=False)
    print(json.dumps({"exit_code": result, **evidence}))
    return 0 if result == 0 and all(evidence.values()) else 1


if __name__ == "__main__":
    raise SystemExit(verify())
