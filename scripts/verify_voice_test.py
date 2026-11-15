"""Native Windows smoke check. Opens mic briefly, then tests manual overlay/audio.

This is not a claim of a successful spoken wake-word detection. The user must
perform that test with `python -m jarvis --voice-test`.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from jarvis.infrastructure.settings import load_settings
from jarvis.ui.voice_test import VoiceTestWindow


def main():
    app = QApplication([])
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet((ROOT / "jarvis/ui/theme.qss").read_text(encoding="utf-8"))
    window = VoiceTestWindow(ROOT, load_settings(ROOT))
    window.show()
    started = time.monotonic()
    evidence = {"real_microphone_frames": 0, "manual_smoke_trigger": False,
                "overlay_visible": False, "overlay_closed_after_five_seconds": False,
                "pcm_bytes": 0, "device_playback_microseconds": 0, "output_level": 0.0}
    timer = QTimer()
    timer.setInterval(100)

    def inspect():
        elapsed = time.monotonic() - started
        if not evidence["manual_smoke_trigger"] and window.received_frames >= 8000:
            evidence["real_microphone_frames"] = window.received_frames
            evidence["manual_smoke_trigger"] = True
            window.activate(manual=True)
        if evidence["manual_smoke_trigger"]:
            evidence["overlay_visible"] |= window.overlay.isVisible()
            evidence["pcm_bytes"] = window.last_pcm_bytes
            evidence["device_playback_microseconds"] = window.speech.played_microseconds
            evidence["output_level"] = window.max_output_level
            if window.triggered_at and time.monotonic() - window.triggered_at > 1 and window.overlay.isVisible():
                folder = ROOT / "data/verification"
                folder.mkdir(exist_ok=True)
                window.grab().save(str(folder / "voice-test-window.png"))
                window.overlay.grab().save(str(folder / "voice-test-brain.png"))
            if window.triggered_at and time.monotonic() - window.triggered_at >= 5.5:
                evidence["overlay_closed_after_five_seconds"] = not window.overlay.isVisible()
                evidence["overlay_duration_seconds"] = round(time.monotonic() - window.triggered_at, 2)
                evidence["output_device"] = window.speech.last_device_name
                window.close()
                timer.stop()
        if elapsed >= 20:
            evidence["error"] = window.status_label.text()
            window.close()
            timer.stop()

    timer.timeout.connect(inspect)
    timer.start()
    app.exec()
    folder = ROOT / "data/verification"
    folder.mkdir(exist_ok=True)
    (folder / "voice-test-smoke.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=True))
    return 0 if all((evidence["real_microphone_frames"] > 0, evidence["overlay_visible"],
                     evidence["overlay_closed_after_five_seconds"], evidence["pcm_bytes"] > 0,
                     evidence["device_playback_microseconds"] > 0)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
