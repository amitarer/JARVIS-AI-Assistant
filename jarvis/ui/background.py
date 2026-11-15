"""System tray lifecycle and process-scoped STOP shortcut; no Windows settings changed."""

import ctypes
import sys
import json
import os
from datetime import datetime, timezone

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


def tray_icon(enabled: bool) -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor("#43d9ec" if enabled else "#8a99a8")
    painter.setPen(QPen(color, 4))
    painter.drawEllipse(5, 5, 54, 54)
    painter.setPen(QPen(color, 5))
    painter.drawLine(24, 20, 43, 20)
    painter.drawLine(36, 20, 36, 39)
    painter.drawArc(21, 31, 15, 15, 180 * 16, 180 * 16)
    painter.end()
    return QIcon(pixmap)


class StopShortcut(QAbstractNativeEventFilter):
    """Ctrl+Alt+Pause works while the dashboard and overlay are both hidden."""
    IDENTIFIER = 0x4A52

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.registered = False
        if sys.platform == "win32":
            self.registered = bool(ctypes.windll.user32.RegisterHotKey(None, self.IDENTIFIER, 0x0002 | 0x0001 | 0x4000, 0x13))
        if self.registered:
            QApplication.instance().installNativeEventFilter(self)

    def nativeEventFilter(self, event_type, message):
        if self.registered:
            from ctypes import wintypes
            event = wintypes.MSG.from_address(int(message))
            if event.message == 0x0312 and event.wParam == self.IDENTIFIER:
                self.callback()
                return True, 0
        return False, 0

    def close(self):
        if self.registered:
            ctypes.windll.user32.UnregisterHotKey(None, self.IDENTIFIER)
            QApplication.instance().removeNativeEventFilter(self)
            self.registered = False


class BackgroundDesktop(QObject):
    def __init__(self, presenter, parent=None):
        super().__init__(parent or presenter.window)
        self.presenter = presenter
        self.window = presenter.window
        self.tray = None
        self.hotkey = None
        self.last_error = ""
        self.telemetry = QTimer(self)
        self.telemetry.setInterval(1000)
        self.telemetry.timeout.connect(self.write_status)
        self.available = QSystemTrayIcon.isSystemTrayAvailable()
        if not self.available:
            return
        self.window.close_to_tray = True
        self.tray = QSystemTrayIcon(tray_icon(False), self)
        self.tray.setToolTip("JARVIS · caricamento · microfono non ancora attivo")
        self.menu = QMenu(self.window)
        self.open_action = self.menu.addAction("Apri conversazione e impostazioni")
        self.open_action.triggered.connect(self.show_dashboard)
        self.mic_action = self.menu.addAction("Microfono ON/OFF")
        self.mic_action.triggered.connect(presenter.toggle_microphone)
        self.stop_action = self.menu.addAction("STOP attività e voce · Ctrl+Alt+Pausa")
        self.stop_action.triggered.connect(presenter.stop)
        self.menu.addSeparator()
        self.quit_action = self.menu.addAction("Esci da JARVIS")
        self.quit_action.triggered.connect(self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        presenter.voice.status.connect(self.tray.setToolTip)
        presenter.voice.enabled_changed.connect(self._microphone)
        presenter.voice.error.connect(self._error)
        presenter.speech.error.connect(self._error)
        self.hotkey = StopShortcut(presenter.stop)
        if not self.hotkey.registered:
            self.stop_action.setText("STOP attività e voce")
        self.tray.show()
        QApplication.instance().setQuitOnLastWindowClosed(False)
        QApplication.instance().aboutToQuit.connect(self.dispose)

    def start(self, *, dashboard=False, auto_listen=True):
        self.telemetry.start()
        self.write_status()
        if dashboard or not self.available:
            self.window.show()
        else:
            self.window.hide()
        self.presenter.start({"kind": "refresh"})
        if auto_listen:
            # Restore the user's device preferences before starting capture.
            self._start_when_loaded()

    def _start_when_loaded(self):
        if self.presenter.closing:
            return
        if self.presenter.worker is not None:
            QTimer.singleShot(100, self._start_when_loaded)
            return
        self.presenter.voice.enable()

    def show_dashboard(self):
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def _activated(self, reason):
        if reason in {QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick}:
            self.show_dashboard()

    def _microphone(self, enabled):
        self.tray.setIcon(tray_icon(enabled))
        self.mic_action.setText("Disattiva microfono" if enabled else "Attiva microfono")

    def _error(self, message):
        self.last_error = message
        self.tray.setToolTip("JARVIS · " + message)
        self.tray.showMessage("JARVIS", message, QSystemTrayIcon.MessageIcon.Warning, 6000)

    def quit(self):
        self.presenter.close()
        self._quit_when_stopped()

    def _quit_when_stopped(self):
        if self.window.allow_close:
            self.dispose()
            QApplication.instance().quit()
        else:
            QTimer.singleShot(50, self._quit_when_stopped)

    def dispose(self):
        self.telemetry.stop()
        self.write_status()
        if self.hotkey:
            self.hotkey.close()
        if self.tray:
            self.tray.hide()

    def write_status(self):
        from jarvis import __version__
        voice = self.presenter.voice
        wake = voice.wake
        payload = {"version": __version__, "pid": os.getpid(), "updated_at": datetime.now(timezone.utc).isoformat(),
                   "phase": voice.phase, "microphone": {"enabled": voice.audio.enabled, "starting": voice.starting,
                   "device": voice.audio.device_name, "samples": voice.audio.captured_samples,
                   "rms": voice.audio.rms, "peak_rms": voice.audio.peak_rms},
                   "wake": {"ready": bool(wake and wake.model_ready), "frames": wake.processed_frames if wake else 0,
                   "score": wake.last_score if wake else None, "peak_score": wake.peak_score if wake else None,
                   "energy_at_peak": wake.energy_at_peak if wake else None,
                   "threshold": wake.gate.threshold if wake else 1 - voice.settings.sensitivity,
                   "detections": wake.detections if wake else 0,
                   "suspended": bool(wake and wake.suspended.is_set()), "error": wake.last_error if wake else ""},
                   "overlay_visible": self.presenter.overlay.isVisible(), "last_error": self.last_error}
        payload["task"]={"active":self.presenter.worker is not None,"autonomy":self.presenter.autonomy_active}
        try:
            root = self.presenter.controller.settings.root
            target = root / "data/runtime.json"
            target.parent.mkdir(exist_ok=True)
            temp = target.with_suffix(".tmp")
            if not temp.resolve().is_relative_to(root.resolve()):
                return
            temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            temp.replace(target)
        except OSError:
            pass
