"""Resolution-independent HUD geometry; no textures or fabricated audio."""

import math
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget


class Visualizer(QWidget):
    COLORS = {"idle": "#43d9ec", "executing": "#53a8ff", "error": "#ff9c7c"}
    LABELS = {"idle": "IN ATTESA", "executing": "OPERAZIONE IN CORSO", "error": "RICHIESTA NON COMPLETATA"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 300)
        self.state = "idle"
        self.reduced_motion = False
        self.suspended = False
        self._phase = 0.0
        self._last = time.monotonic()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._advance)
        self.setAccessibleName("Visualizzatore di stato JARVIS")

    def set_state(self, state: str) -> None:
        self.state = state if state in self.COLORS else "idle"
        self._sync_timer()
        self.update()

    def set_reduced_motion(self, enabled: bool) -> None:
        self.reduced_motion = enabled
        self._sync_timer()
        self.update()

    def set_suspended(self, suspended: bool) -> None:
        self.suspended = suspended
        self._sync_timer()

    def _sync_timer(self) -> None:
        self.timer.stop()
        self._last = time.monotonic()
        if self.isVisible() and not self.reduced_motion and not self.suspended:
            self.timer.start(50 if self.state == "idle" else 33)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event) -> None:
        self.timer.stop()
        super().hideEvent(event)

    def _advance(self) -> None:
        current = time.monotonic()
        speed = 6 if self.state == "idle" else 42
        self._phase = (self._phase + (current - self._last) * speed) % 360
        self._last = current
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(self.width(), self.height())
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(size / 480, size / 480)
        cyan = QColor(self.COLORS[self.state])
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#112936"), 1))
        painter.drawEllipse(QRectF(-214, -214, 428, 428))
        painter.drawEllipse(QRectF(-184, -184, 368, 368))
        for i in range(96):
            angle = math.radians(i * 3.75)
            radius = 204 if i % 4 == 0 else 209
            color = QColor(cyan)
            color.setAlpha(135 if i % 4 == 0 else 40)
            painter.setPen(QPen(color, 1.3))
            painter.drawLine(radius * math.cos(angle), radius * math.sin(angle),
                             214 * math.cos(angle), 214 * math.sin(angle))
        for radius, start, length, width, alpha in (
            (194, self._phase, 64, 2.5, 190), (194, self._phase + 180, 64, 2.5, 190),
            (169, -self._phase * 1.4 + 40, 110, 1.3, 140),
            (169, -self._phase * 1.4 + 220, 70, 1.3, 140),
            (142, self._phase * 0.5 + 70, 210, 1, 80),
        ):
            color = QColor(cyan)
            color.setAlpha(alpha)
            painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(QRectF(-radius, -radius, radius * 2, radius * 2), int(start * 16), int(length * 16))
        for radius, alpha in ((130, 8), (124, 12), (118, 19)):
            color = QColor(cyan)
            color.setAlpha(alpha)
            painter.setPen(QPen(color, 8))
            painter.drawEllipse(QRectF(-radius, -radius, radius * 2, radius * 2))
        painter.setPen(QPen(cyan, 1.3))
        painter.drawEllipse(QRectF(-112, -112, 224, 224))
        font = QFont("Segoe UI", 25, QFont.Weight.Light)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 6)
        painter.setFont(font)
        painter.setPen(QColor("#e4f9ff"))
        painter.drawText(QRectF(-110, -34, 220, 50), Qt.AlignmentFlag.AlignCenter, "JARVIS")
        painter.setFont(QFont("Consolas", 8))
        painter.setPen(cyan)
        painter.drawText(QRectF(-120, 22, 240, 24), Qt.AlignmentFlag.AlignCenter, "L O C A L  A I  /  0 . 3")
        painter.setPen(QColor("#91adbb"))
        painter.drawText(QRectF(-190, 151, 380, 22), Qt.AlignmentFlag.AlignCenter, self.LABELS[self.state])
