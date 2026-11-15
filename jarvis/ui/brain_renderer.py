"""Projected cortical geometry and neural signals, rendered only while visible."""

import math
import random

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient


class BrainRenderer:
    def __init__(self):
        rng = random.Random(704)
        self.nodes: list[tuple[float, float, float, int]] = []
        self.edges: list[tuple[int, int]] = []
        for side in (-1, 1):
            first = len(self.nodes)
            for row in range(1, 19):
                theta = math.pi * row / 19
                for column in range(24):
                    phi = math.tau * column / 24
                    folds = 1 + 0.065 * math.sin(9 * theta + 3 * phi) + 0.045 * math.cos(11 * phi - 4 * theta)
                    x = side * (0.10 + (0.57 + 0.55 * math.cos(phi)) * math.sin(theta) * folds)
                    y = 0.86 * math.cos(theta) * folds + 0.09 * math.sin(phi)
                    z = 0.72 * math.sin(phi) * math.sin(theta) * folds
                    self.nodes.append((x, y, z, side))
                    index = len(self.nodes) - 1
                    if column:
                        self.edges.append((index - 1, index))
                    if row > 1 and column % 2 == 0:
                        self.edges.append((index - 24, index))
            # A few internal structures give volume through the transparent cortex.
            for _ in range(36):
                index = len(self.nodes)
                self.nodes.append((side * rng.uniform(0.15, 0.7), rng.uniform(-0.5, 0.5), rng.uniform(-0.4, 0.4), side))
                target = min(range(first, index), key=lambda i: sum((self.nodes[i][j] - self.nodes[index][j]) ** 2 for j in range(3)))
                self.edges.append((target, index))

    def paint(self, painter: QPainter, bounds: QRectF, phase: float, amplitude: float, state: str):
        scale = min(bounds.width() / 3.1, bounds.height() / 2.5)
        cx, cy = bounds.center().x(), bounds.center().y()
        angle = 0.42 + math.sin(phase * 0.22) * 0.42
        tilt = math.sin(phase * 0.15) * 0.07 - 0.08
        pulse = 1 + min(1, amplitude) * 0.045 + math.sin(phase * 1.2) * 0.006
        color = QColor("#ff886c" if state == "error" else "#4ee6ff")
        glow = QRadialGradient(QPointF(cx, cy), scale * 1.35)
        for position, alpha in ((0, 22), (0.6, 9), (1, 0)):
            tint = QColor(color)
            tint.setAlpha(alpha + int(amplitude * 10) if position != 1 else 0)
            glow.setColorAt(position, tint)
        painter.setPen(QPen(QColor(0, 0, 0, 0), 0))
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), scale * 1.5, scale * 1.3)
        projected = []
        for x, y, z, side in self.nodes:
            xr = x * math.cos(angle) + z * math.sin(angle)
            zr = -x * math.sin(angle) + z * math.cos(angle)
            yr = y * math.cos(tilt) - zr * math.sin(tilt)
            depth = y * math.sin(tilt) + zr * math.cos(tilt)
            perspective = 3.8 / (3.8 - depth)
            projected.append((QPointF(cx + xr * scale * perspective * pulse, cy - yr * scale * perspective * pulse), depth))
        painter.setBrush(QColor(0, 0, 0, 0))
        for index, (a, b) in enumerate(self.edges):
            point_a, depth_a = projected[a]
            point_b, depth_b = projected[b]
            front = (depth_a + depth_b + 1.6) / 3.2
            tint = QColor(color)
            tint.setAlpha(max(12, min(120, int(22 + front * 60 + amplitude * 25))))
            painter.setPen(QPen(tint, 0.65))
            painter.drawLine(point_a, point_b)
            if index % 17 == 0:
                travel = (phase * (0.9 if state == "thinking" else 0.3) + index * 0.137) % 1
                position = point_a * (1 - travel) + point_b * travel
                painter.setPen(QPen(color, 1.4 + amplitude))
                painter.drawPoint(position)
        for index in sorted(range(len(projected)), key=lambda i: projected[i][1]):
            if index % 3:
                continue
            point, depth = projected[index]
            tint = QColor(color)
            tint.setAlpha(max(30, min(220, int(100 + depth * 95 + amplitude * 35))))
            painter.setPen(QPen(tint, 1.4 + amplitude * 0.9))
            painter.drawPoint(point)
