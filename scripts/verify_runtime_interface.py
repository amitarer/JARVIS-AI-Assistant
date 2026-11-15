"""Native dashboard/overlay/PCM/activation checks, using an isolated test DB.

No AI call, microphone capture or desktop tool is executed. Voice state changes
are injected into the real Presenter; the WAV is real local Cosimo PCM.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QObject, QPoint, Qt
from PySide6.QtMultimedia import QAudioFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

from jarvis.core.models import Event
from jarvis.ui.main_window import MainWindow
from jarvis.ui.presenter import Presenter
from jarvis.ui.startup import InstanceChannel
from tests.support import make_controller, temporary_project


def main():
    folder = ROOT / "data/verification/runtime-integration"
    folder.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet((ROOT / "jarvis/ui/theme.qss").read_text(encoding="utf-8"))
    temporary = temporary_project()
    window = MainWindow()
    presenter = Presenter(window, make_controller(Path(temporary.name)))
    checks = {}
    snapshots = {}

    def until(predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("Native UI operation timed out")

    def snapshot(view):
        values = []
        view.snapshot(values.append)
        until(lambda: values)
        return values[0]

    try:
        window.show()
        until(lambda: window.visualizer.view and window.visualizer.view.initialized)
        until(lambda: snapshot(window.visualizer.view).get("frames", 0) > 20)
        surface = window.visualizer
        checks["only_one_dashboard_renderer_after_native_show"] = len(surface.findChildren(QWebEngineView)) == 1
        snapshots["idle"] = snapshot(surface.view)
        checks["normal_dashboard_amber_webgl"] = snapshots["idle"].get("style") == "organic" and snapshots["idle"].get("running")
        window.screen().grabWindow(window.winId()).save(str(folder / "dashboard-initial.png"))
        surface.zoom.setValue(230)
        until(lambda: snapshot(surface.view).get("zoom") == 2.3)
        checks["dashboard_zoom"] = True
        surface.view.set_rotation(False)
        surface.set_reduced_motion(True)
        picked = []
        surface.view.page().runJavaScript(
            "window.neural.selectNeuron(1100);window.neural.focusNeuron();window.neural.selectNeuron(-1);"
            "JSON.stringify(window.neural.screenPosition(1100))", picked.append)
        until(lambda: picked)
        point = json.loads(picked[0])
        QTest.mouseClick(surface.view.focusProxy(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(round(point["x"]), round(point["y"])))
        until(lambda: snapshot(surface.view).get("selected", -1) >= 0)
        until(lambda: "connessioni" in surface.inspector.text())
        checks["actual_click_shows_node_information"] = True
        window.screen().grabWindow(window.winId()).save(str(folder / "dashboard.png"))
        surface.set_reduced_motion(False)
        surface.view.set_rotation(True)
        presenter._wake_activated()
        overlay = presenter.overlay
        until(lambda: overlay.surface.view and overlay.surface.view.initialized)
        checks["wake_opens_live_amber_overlay"] = overlay.isVisible() and snapshot(overlay.surface.view).get("style") == "organic"
        checks["overlay_click_through"] = bool(overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput)

        pcm = ROOT / "data/voice-reference/cosimo_neutro.wav"
        with wave.open(str(pcm), "rb") as source:
            fmt = QAudioFormat()
            fmt.setSampleRate(source.getframerate())
            fmt.setChannelCount(source.getnchannels())
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            data = source.readframes(source.getnframes())
        presenter.voice_turn = True
        levels = []
        presenter.speech.level.connect(levels.append)
        presenter.speech.play_pcm(data, fmt)
        if presenter.speech.sink:
            presenter.speech.sink.setVolume(0)
        until(lambda: presenter.speech.active and any(level > 0.02 for level in levels))
        until(lambda: snapshot(overlay.surface.view).get("audio", 0) > 0.01)
        snapshots["real_pcm"] = snapshot(overlay.surface.view)
        checks["real_pcm_to_operational_overlay"] = snapshots["real_pcm"].get("state") == "speaking"
        checks["real_pcm_to_dashboard"] = snapshot(surface.view).get("audio", 0) > 0.01
        overlay.grab().save(str(folder / "overlay.png"))
        presenter.stop()
        until(lambda: presenter.speech.is_stopped())
        checks["stop_releases_audio_and_overlay"] = not overlay.isVisible()
        overlay.present("thinking")
        ack = threading.Event()
        presenter.on_event(Event("execution_barrier", {"ack": ack, "tool": "open_application"}))
        checks["hidden_before_action_acknowledgement"] = ack.is_set() and not overlay.isVisible()
        until(lambda: not snapshot(overlay.surface.view).get("running"))
        checks["hidden_overlay_gpu_suspended"] = True
        surface.set_suspended(True)
        until(lambda: not snapshot(surface.view).get("running"))
        checks["dashboard_suspension"] = True
        surface.set_suspended(False)

        class Desktop(QObject):
            shows = 0
            quits = 0

            def show_dashboard(self):
                self.shows += 1
                window.show()

            def quit(self):
                self.quits += 1

        desktop = Desktop()
        channel = InstanceChannel(Path(temporary.name), desktop)
        for action in ("show", "quit"):
            child_code = ("from PySide6.QtCore import QCoreApplication;from jarvis.ui.startup import request_existing;"
                          "app=QCoreApplication([]);import sys;sys.exit(0 if request_existing(sys.argv[1],sys.argv[2],timeout=1500) else 1)")
            child = subprocess.Popen([sys.executable, "-B", "-c", child_code, temporary.name, action], cwd=ROOT)
            until(lambda: child.poll() is not None)
            assert child.returncode == 0
        until(lambda: desktop.shows == 1 and desktop.quits == 1)
        checks["second_process_activation_and_graceful_quit"] = True
        channel.server.close()
        surface._failed("Synthetic context-loss fallback check")
        checks["webgl_failure_keeps_app_usable"] = surface.fallback is not None
        checks["agents_panel_available_in_main_window"] = window.agents_button.isVisible()
        report = {"passed": all(checks.values()), "checks": checks, "snapshots": snapshots,
                  "microphone_started": False, "model_calls": 0, "production_db_used": False,
                  "state_injection_is_test_only": True}
        (folder / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "checks": checks}))
        return 0 if report["passed"] else 1
    finally:
        presenter.close()
        until(lambda: window.allow_close)
        window.deleteLater()
        app.processEvents()
        temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
