"""Actual Windows/WebGL preview checks; does not start Ollama or audio capture.

GPU samples are total device usage, not per-process. GPU render times are queried
asynchronously by WebGL when EXT_disjoint_timer_query_webgl2 is available.
"""

import json
import argparse
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from jarvis.ui.neural_preview import NeuralPreviewWindow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--style", choices=("organic", "cortex"), default="organic")
    parser.add_argument("--with-local-pcm", action="store_true")
    args = parser.parse_args()
    folder = ROOT / ("data/verification/neural-preview" if args.style == "organic" else "data/verification/neural-preview-cortex")
    folder.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = NeuralPreviewWindow(style=args.style)
    errors = []
    window.view.failed.connect(errors.append)
    window.overlay.view.failed.connect(errors.append)
    evidence = {"simulation": True, "ollama_started": False, "microphone_started": False,
                "gpu_samples_scope": "total device, including other processes", "errors": errors,
                "checks": {}, "snapshots": {}, "gpu_samples": []}
    completed = threading.Event()

    def sample_gpu():
        executable = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/nvidia-smi.exe"
        if not executable.is_file():
            return
        while not completed.is_set():
            try:
                result = subprocess.run([str(executable), "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                                         "--format=csv,noheader,nounits"], capture_output=True, text=True,
                                        timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if result.returncode == 0:
                    evidence["gpu_samples"].append({"elapsed_s": round(time.monotonic() - started, 2),
                                                     "csv": result.stdout.strip()})
            except (OSError, subprocess.TimeoutExpired):
                pass
            completed.wait(1)

    started = time.monotonic()
    threading.Thread(target=sample_gpu, daemon=True).start()
    window.show()
    backdrop = QWidget()
    backdrop.setWindowTitle("JARVIS · Test trasparenza controllato")
    backdrop.setStyleSheet("background: #173c2c;")
    stage = 0
    due = started + 8
    pending = False
    old_frames = 0
    first_yaw = 0
    pcm_levels = []

    def check(name, condition):
        evidence["checks"][name] = bool(condition)

    def save_snapshot(name, callback):
        nonlocal pending
        pending = True
        def received(data):
            nonlocal pending
            evidence["snapshots"][name] = data
            callback(data)
            pending = False
        window.view.snapshot(received)

    def finish():
        timer.stop()
        completed.set()
        evidence["passed"] = bool(evidence["checks"]) and all(evidence["checks"].values()) and not errors
        evidence["elapsed_s"] = round(time.monotonic() - started, 2)
        (folder / "verification.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(evidence, ensure_ascii=True, indent=2), flush=True)
        backdrop.close()
        window.close()
        app.quit()

    def tick():
        nonlocal stage, due, old_frames, first_yaw
        now = time.monotonic()
        if now - started > 55:
            check("completed_before_timeout", False)
            finish()
            return
        if pending or now < due:
            return
        if not window.view.initialized or not window.overlay.view.initialized:
            return
        if stage == 0:
            def received(data):
                nonlocal first_yaw
                check("webgl2_ready", data.get("ready") and "WebGL 2" in data.get("version", ""))
                check("alpha_context", data.get("alpha"))
                check("requested_style", data.get("style") == args.style)
                check("filament_geometry", data.get("filaments", 0) >= 16 if args.style == "organic" else data.get("filaments") == 0)
                check("near_60_fps", data.get("fps", 0) >= 55)
                check("small_graph_buffers", 0 < data.get("graphBytes", 0) < 2_000_000)
                first_yaw = data.get("yaw", 0)
                window.grab().save(str(folder / "preview.png"))
            save_snapshot("thinking", received)
            stage = 1; due = now + 1
        elif stage == 1:
            def received(data):
                check("true_rotation", abs(data.get("yaw", 0) - first_yaw) > 0.02)
            save_snapshot("rotated", received)
            window.rotation.setChecked(False)
            window.select_state("listening")
            window.amplitude.setValue(65)
            stage = 2; due = now + 0.7
        elif stage == 2:
            save_snapshot("manual_listening", lambda data: check("audio_bridge", 0.55 < data.get("audio", 0) < 0.75))
            window.select_state("speaking")
            window.amplitude.setValue(35)
            window.zoom.setValue(200)
            stage = 3; due = now + 0.7
        elif stage == 3:
            save_snapshot("manual_speaking", lambda data: (
                check("speaking_bridge", 0.25 < data.get("audio", 0) < 0.45)))
            # Atomic check remains deterministic if the user explores the visible preview.
            window.view.page().runJavaScript("window.neural.setZoom(2); window.neural.snapshot().zoom",
                                             lambda value: check("zoom", value == 2))
            window.amplitude.setValue(0)
            window.reduced.setChecked(True)
            # Query the same projection used by picking, then click the actual canvas.
            def click_node(value):
                point = json.loads(value)
                QTest.mouseClick(window.view.focusProxy(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                                 QPoint(round(point["x"]), round(point["y"])))
            window.view.page().runJavaScript(
                "window.neural.selectNeuron(1100); window.neural.focusNeuron(); "
                "window.neural.selectNeuron(-1); JSON.stringify(window.neural.screenPosition(1100))", click_node)
            stage = 4; due = now + 0.8
        elif stage == 4:
            def received(data):
                selected = data.get("selected", -1)
                check("click_picks_neuron", selected >= 0)
                check("inspector_matches_graph", selected >= 0 and f"N-{selected:04d}" in window.inspector.text())
                check("real_neighbors_in_inspector", selected >= 0 and "sinapsi" in window.inspector.text())
                window.grab().save(str(folder / "neuron-inspector.png"))
                window.view.page().runJavaScript(
                    "window.neural.focusNeuron(); JSON.stringify(window.neural.screenPosition(window.neural.snapshot().selected))",
                    lambda value: check("focus_centers_selected_neuron", bool(value) and
                                        abs(json.loads(value)["x"] - window.view.width() / 2) < 1 and
                                        abs(json.loads(value)["y"] - window.view.height() / 2) < 1))
            save_snapshot("selected_neuron", received)
            stage = 5; due = now + 0.4
        elif stage == 5:
            window.select_state("executing")
            check("executing_hides_overlay", not window.overlay.isVisible())
            stage = 6; due = now + 0.4
        elif stage == 6:
            def received(data):
                nonlocal old_frames
                old_frames = data.get("frames", 0)
                check("executing_stops_loop", not data.get("running"))
            save_snapshot("executing", received)
            stage = 7; due = now + 0.8
        elif stage == 7:
            save_snapshot("still_executing", lambda data: check("no_background_frames", data.get("frames") == old_frames))
            window.select_state("confirmation")
            stage = 8; due = now + 0.5
        elif stage == 8:
            save_snapshot("confirmation", lambda data: check("confirmation_state", data.get("state") == "confirmation"))
            window.select_state("error")
            stage = 9; due = now + 0.5
        elif stage == 9:
            save_snapshot("error", lambda data: check("error_state", data.get("state") == "error"))
            window.select_state("idle")
            stage = 10; due = now + 0.4
        elif stage == 10:
            save_snapshot("idle", lambda data: check("idle_stops_loop", not data.get("running")))
            window.select_state("thinking")
            window.hide()
            stage = 11; due = now + 0.5
        elif stage == 11:
            save_snapshot("hidden", lambda data: check("hidden_stops_loop", not data.get("running")))
            screen = app.primaryScreen()
            area = screen.availableGeometry()
            backdrop.resize(760, 640)
            backdrop.move(area.center() - backdrop.rect().center())
            backdrop.show(); backdrop.raise_()
            window.overlay.present("thinking", screen)
            stage = 12; due = now + 2
        elif stage == 12:
            overlay = window.overlay
            screen = overlay.screen()
            rect = overlay.frameGeometry()
            shot = screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height())
            shot.save(str(folder / "overlay-composited.png"))
            image = shot.toImage()
            dpr = shot.devicePixelRatio()
            corners = [(16, 16), (rect.width() - 16, 16), (16, rect.height() - 44)]
            colors = [image.pixelColor(round(x * dpr), round(y * dpr)).name() for x, y in corners]
            evidence["transparency_corner_colors"] = colors
            evidence["screens"] = [{"name": s.name(), "dpr": s.devicePixelRatio(),
                                    "geometry": [s.geometry().x(), s.geometry().y(), s.geometry().width(), s.geometry().height()]}
                                   for s in app.screens()]
            check("desktop_transparency", all(color == "#173c2c" for color in colors))
            check("click_through_flag", bool(overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput))
            overlay.dismiss()
            stage = 13; due = now + 0.5
        elif stage == 13:
            def received(data):
                evidence["snapshots"]["overlay_hidden"] = data
                check("overlay_hidden_stops_loop", not data.get("running"))
                check("overlay_hidden", not window.overlay.isVisible())
                if args.with_local_pcm:
                    window.show()
                    window.play_sample(volume=0)
                    if window.sample_player is not None:
                        window.sample_player.level.connect(pcm_levels.append)
                else:
                    finish()
            window.overlay.view.snapshot(received)
            stage = 14; due = now + 1.5
        elif stage == 14 and args.with_local_pcm:
            def received(data):
                player = window.sample_player
                check("local_pcm_playing", player is not None and player.sink is not None and player.played_microseconds > 100000)
                check("pcm_meter_varies", len(pcm_levels) >= 8 and max(pcm_levels) - min(pcm_levels) > 0.02)
                check("pcm_drives_speaking_state", data.get("state") == "speaking" and not window.audio_timer.isActive())
                evidence["pcm_meter_peak"] = max(pcm_levels, default=0)
                evidence["muted_pcm_test"] = True
                window.stop()
            save_snapshot("actual_local_pcm", received)
            stage = 15; due = now + 0.4
        elif stage == 15 and args.with_local_pcm:
            save_snapshot("after_pcm_stop", lambda data: (
                check("pcm_stop_releases_sink", window.sample_player is not None and window.sample_player.sink is None),
                check("pcm_stop_suspends_renderer", not data.get("running"))))
            stage = 16; due = now + 0.3
        elif stage == 16 and args.with_local_pcm:
            finish()

    timer = QTimer()
    timer.setInterval(100)
    timer.timeout.connect(tick)
    timer.start()
    app.exec()
    return 0 if evidence.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
