"""Check native audio setup and STOP with a muted sample; no microphone or AI."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication
from jarvis.ui.voice_comparison import VoiceComparisonWindow


def main():
    app = QApplication([])
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet((ROOT / "jarvis/ui/theme.qss").read_text(encoding="utf-8"))
    window = VoiceComparisonWindow(ROOT)
    errors = []
    window.player.error.connect(errors.append)
    window.show()
    evidence = {"muted_hardware_test": True}

    def begin():
        window.volume.setValue(0)
        window.play_prepared()
        QTimer.singleShot(400, finish)

    def finish():
        evidence.update(window.player.playback_diagnostics)
        window.stop()
        evidence["processed_microseconds"] = window.player.played_microseconds
        evidence["stop_released_audio"] = window.player.sink is None and not window.player.active
        evidence["errors"] = errors
        window.volume.setValue(85)
        folder = ROOT / "data/voice-comparison"
        window.grab().save(str(folder / "comparison-window.png"))
        (folder / "playback-verification.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(evidence, ensure_ascii=True))
        window.close()

    QTimer.singleShot(100, begin)
    app.exec()
    return 0 if evidence.get("stop_released_audio") and evidence.get("processed_microseconds", 0) > 0 and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
