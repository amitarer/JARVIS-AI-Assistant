"""Transient, non-activating desktop overlay with real-time procedural graphics."""

import ctypes
import sys
import time

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from jarvis.core.assistant_state import AssistantState
from jarvis.ui.brain_renderer import BrainRenderer


def active_screen():
    if sys.platform == "win32":
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
        rect = RECT()
        handle = user32.GetForegroundWindow()
        if handle and user32.GetWindowRect(handle, ctypes.byref(rect)):
            from PySide6.QtCore import QPoint
            screen = QGuiApplication.screenAt(QPoint((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2))
            if screen:
                return screen
    return QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()


class BrainOverlay(QWidget):
    LABELS = {"listening": "TI ASCOLTO", "thinking": "ELABORAZIONE LOCALE", "speaking": "JARVIS",
              "confirmation": "AUTORIZZAZIONE RICHIESTA", "error": "ATTENZIONE"}

    def __init__(self, parent=None):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus |
                         Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setWindowTitle("JARVIS · Overlay")
        self.resize(540, 510)
        self.renderer = BrainRenderer()
        self.state = AssistantState.IDLE
        self.caption = ""
        self.preview = False
        self.level = 0.0
        self.target_level = 0.0
        self.reduced_motion = False
        self.phase = 0.0
        self.last_tick = time.monotonic()
        self.frame_timer = QTimer(self)
        self.frame_timer.setInterval(33)
        self.frame_timer.timeout.connect(self._tick)
        self.expiry = QTimer(self)
        self.expiry.setSingleShot(True)
        self.expiry.timeout.connect(self.dismiss)
        self.fade = QPropertyAnimation(self, b"windowOpacity", self)
        self.fade.setDuration(180)
        self.fade.setEasingCurve(QEasingCurve.Type.OutCubic)

    def present(self, state: str, caption: str = "", *, preview: bool = False, timeout_ms: int = 180000):
        self.state = AssistantState(state)
        if self.state in {AssistantState.IDLE, AssistantState.EXECUTING, AssistantState.CONFIRMATION}:
            self.dismiss()
            return
        self.caption, self.preview = caption[:240], preview
        if not self.isVisible():
            screen = active_screen()
            if screen:
                area = screen.availableGeometry()
                self.resize(min(540, area.width()), min(510, area.height()))
                self.move(area.center() - self.rect().center())
            self.setWindowOpacity(0 if not self.reduced_motion else 1)
            self.show()
            if not self.reduced_motion:
                self.fade.setStartValue(0.0)
                self.fade.setEndValue(1.0)
                self.fade.start()
        self.last_tick = time.monotonic()
        if not self.reduced_motion:
            self.frame_timer.start()
        self.expiry.start(5000 if self.state is AssistantState.ERROR else timeout_ms)
        self.update()

    def dismiss(self):
        self.fade.stop()
        self.frame_timer.stop()
        self.expiry.stop()
        self.level = self.target_level = 0
        self.hide()

    def set_level(self, level: float):
        self.target_level = max(0, min(1, float(level)))
        if self.reduced_motion and self.isVisible():
            self.level = self.target_level
            self.update()

    def set_reduced_motion(self, enabled: bool):
        self.reduced_motion = enabled
        if enabled:
            self.frame_timer.stop()
            self.fade.stop()
            self.setWindowOpacity(1)
        elif self.isVisible():
            self.frame_timer.start()
        self.update()

    def _tick(self):
        now = time.monotonic()
        self.phase += min(0.1, now - self.last_tick)
        self.last_tick = now
        self.level += (self.target_level - self.level) * 0.3
        self.update()

    def hideEvent(self, event):
        self.frame_timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        self.renderer.paint(painter, QRectF(16, 10, self.width() - 32, self.height() - 125), self.phase, self.level, self.state)
        painter.setPen(QColor("#a4f3ff"))
        painter.setFont(QFont("Consolas", 11))
        painter.drawText(QRectF(20, self.height() - 110, self.width() - 40, 30), Qt.AlignmentFlag.AlignCenter,
                         "ANTEPRIMA · ATTIVAZIONE MANUALE" if self.preview else self.LABELS.get(self.state, "JARVIS"))
        painter.setPen(QColor("#deeff7"))
        painter.setFont(QFont("Segoe UI", 10))
        if self.caption:
            painter.fillRect(QRectF(30, self.height() - 74, self.width() - 60, 65), QColor(5, 16, 27, 220))
            painter.drawText(QRectF(42, self.height() - 70, self.width() - 84, 58),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.caption)
