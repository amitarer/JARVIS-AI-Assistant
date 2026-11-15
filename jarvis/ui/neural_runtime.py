"""Live amber renderer shared by the desktop dashboard and voice overlay."""

from functools import lru_cache
import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from jarvis.core.assistant_state import AssistantState
from jarvis.ui.overlay import BrainOverlay, active_screen
from jarvis.ui.visualizer import Visualizer


@lru_cache(maxsize=1)
def organic_graph():
    from jarvis.ui.neural_organic import build_organic_graph
    return build_organic_graph(4800)


class NeuralVisualizer(QWidget):
    LABELS = {"idle": "IN ATTESA", "executing": "OPERAZIONE IN CORSO", "error": "ATTENZIONE",
              "listening": "TI ASCOLTO", "thinking": "QWEN · GENERAZIONE", "speaking": "RISPOSTA VOCALE",
              "confirmation": "CONFERMA RICHIESTA"}

    def __init__(self, parent=None, *, interactive=True):
        super().__init__(parent)
        self.interactive = interactive
        self.state, self.reduced_motion, self.suspended = "idle", False, False
        self.view = self.fallback = None
        self.initializing = False
        self.failure = ""
        self.disposed = False
        self.pending_snapshot = False
        self.level = 0.0
        self.setMinimumSize(300, 300)
        self.setAccessibleName("Nucleo neurale ambra 3D interattivo")
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(0, 0, 0, 0)
        self.loading = QLabel("Caricamento nucleo neurale 3D…")
        self.loading.setFixedHeight(24)
        self.loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout_box.addWidget(self.loading)
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self._poll)
        if interactive:
            controls = QHBoxLayout()
            controls.addWidget(QLabel("Zoom"))
            self.zoom = QSlider(Qt.Orientation.Horizontal)
            self.zoom.setRange(50, 600)
            self.zoom.setValue(100)
            self.zoom.setAccessibleName("Zoom nucleo neurale da 0,5 a 6 volte")
            self.zoom.valueChanged.connect(lambda value: self.view and self.view._call("setZoom", value / 100))
            controls.addWidget(self.zoom, 1)
            self.zoom_label = QLabel("1.00×")
            controls.addWidget(self.zoom_label)
            reset = QPushButton("Centra")
            reset.clicked.connect(lambda: self.view and self.view._call("resetView", None))
            controls.addWidget(reset)
            self.layout_box.addLayout(controls)
            self.inspector = QLabel("Rotella: zoom · Trascina: ruota · Clicca un nodo per le informazioni.\nRete grafica procedurale, distinta dai neuroni interni di Qwen.")
            self.inspector.setWordWrap(True)
            self.inspector.setMinimumHeight(64)
            self.inspector.setTextFormat(Qt.TextFormat.PlainText)
            self.inspector.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.layout_box.addWidget(self.inspector)

    def _initialize(self):
        if self.view or self.fallback or self.disposed or self.initializing:
            return
        # WebEngine startup processes native show events during construction.
        # Guard against a second showEvent creating another view before the
        # first constructor returns and assigns self.view.
        self.initializing = True
        try:
            from jarvis.ui.neural_preview import NeuralView
            self.view = NeuralView(organic_graph(), fps=30, pixel_ratio=1.25,
                                   render_idle=self.interactive, parent=self)
            self.view.setMinimumHeight(260 if self.interactive else 300)
            if self.interactive:
                # Match the opaque dashboard. Only the separate top-level
                # voice overlay needs desktop transparency.
                self.view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
                self.view.setStyleSheet("background:#080f17;border:none;")
                self.view.page().setBackgroundColor(QColor("#080f17"))
            self.layout_box.insertWidget(0, self.view, 1)
            self.view.ready.connect(self._ready)
            self.view.failed.connect(self._failed)
            if not self.interactive:
                self.view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.view.set_state(self.state)
            self.view.set_reduced_motion(self.reduced_motion)
        except Exception:
            logging.getLogger("jarvis").exception("Live neural renderer could not load")
            self._failed("Renderer 3D non disponibile")
        finally:
            self.initializing = False

    def _ready(self):
        if self.disposed or self.fallback:
            return
        self.loading.hide()
        self.view.set_state(self.state)
        self.view.set_level(self.level)
        self._sync()

    def _failed(self, reason):
        if self.fallback or self.disposed:
            return
        self.failure = str(reason)[:500]
        logging.getLogger("jarvis").warning("Neural renderer fallback: %s", self.failure)
        if self.view:
            self.view.suspend()
            self.view.hide()
        self.loading.setText("Grafica di compatibilità · WebGL non disponibile")
        self.loading.show()
        self.fallback = Visualizer(self)
        self.layout_box.insertWidget(0, self.fallback, 1)
        self.fallback.set_state(self.state)
        self.fallback.set_reduced_motion(self.reduced_motion)
        self._sync()

    def set_state(self, state):
        self.state = state if state in self.LABELS else "idle"
        self.level = 0.0
        if self.view and not self.fallback:
            self.view.set_state(self.state)
        if self.fallback:
            self.fallback.set_state(self.state)
        self._sync()

    def set_level(self, level):
        self.level = max(0.0, min(1.0, float(level)))
        if self.view and not self.fallback and not self.disposed:
            self.view.set_level(self.level)

    def set_reduced_motion(self, enabled):
        self.reduced_motion = bool(enabled)
        if self.view and not self.disposed:
            self.view.set_reduced_motion(enabled)
        if self.fallback:
            self.fallback.set_reduced_motion(enabled)
        self._sync()

    def set_suspended(self, enabled):
        self.suspended = bool(enabled)
        self._sync()

    def _sync(self):
        self.timer.stop()
        active = self.isVisible() and not self.suspended and not self.disposed
        if self.view and not self.fallback and not self.disposed:
            self.view.resume() if active else self.view.suspend()
            if active and self.interactive:
                self.timer.start()
        if self.fallback:
            self.fallback.set_suspended(not active)

    def _poll(self):
        if not self.view or self.pending_snapshot or self.disposed:
            return
        self.pending_snapshot = True

        def received(stats):
            self.pending_snapshot = False
            if self.disposed or not stats.get("ready"):
                return
            zoom = stats.get("zoom", 1)
            self.zoom.blockSignals(True)
            self.zoom.setValue(round(zoom * 100))
            self.zoom.blockSignals(False)
            self.zoom_label.setText(f"{zoom:.2f}×")
            index = stats.get("selected", -1)
            if type(index) is int and 0 <= index < len(self.view.graph.positions):
                point = self.view.graph.positions[index]
                neighbors = sorted(b if a == index else a for a, b in self.view.graph.edges if index in (a, b))
                self.inspector.setText(f"N-{index:04d} · {len(neighbors)} connessioni\n"
                    f"x {point[0]:+.3f} · y {point[1]:+.3f} · z {point[2]:+.3f}\n"
                    "Collegato a: " + ", ".join(f"N-{value:04d}" for value in neighbors) + " · Dati della rete grafica.")
            else:
                self.inspector.setText("Rotella: zoom · Trascina: ruota · Clicca un nodo per le informazioni.\n"
                                       "Rete grafica procedurale, distinta dai neuroni interni di Qwen.")
        self.view.snapshot(received)

    def showEvent(self, event):
        super().showEvent(event)
        self._initialize()
        self._sync()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.timer.stop()
        if self.view and not self.disposed:
            self.view.suspend()

    def dispose(self):
        if self.disposed:
            return
        self.timer.stop()
        if self.view:
            self.view.dispose()
            # QWebEnginePage must be destroyed before its private profile.
            from shiboken6 import delete
            delete(self.view.page())
        self.disposed = True


class NeuralBrainOverlay(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus |
                         Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setWindowTitle("JARVIS · Nucleo neurale")
        self.state = AssistantState.IDLE
        self.reduced_motion = False
        layout = QVBoxLayout(self)
        self.surface = NeuralVisualizer(self, interactive=False)
        layout.addWidget(self.surface, 1)
        self.caption_label = QLabel()
        self.caption_label.setTextFormat(Qt.TextFormat.PlainText)
        self.caption_label.setWordWrap(True)
        self.caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption_label.setStyleSheet("color:#f4d5a7;background:transparent;font:13px 'Segoe UI';")
        layout.addWidget(self.caption_label)
        self.expiry = QTimer(self)
        self.expiry.setSingleShot(True)
        self.expiry.timeout.connect(self.dismiss)

    def present(self, state, caption="", *, preview=False, timeout_ms=180000):
        self.state = AssistantState(state)
        if self.state in {AssistantState.IDLE, AssistantState.EXECUTING, AssistantState.CONFIRMATION}:
            self.dismiss()
            return
        self.surface.set_state(state)
        self.caption_label.setText(("ANTEPRIMA · " if preview else "") + BrainOverlay.LABELS.get(state, "JARVIS") +
                                   ("\n" + caption[:240] if caption else ""))
        if not self.isVisible():
            screen = active_screen()
            if screen:
                area = screen.availableGeometry()
                self.resize(min(680, area.width()), min(560, area.height()))
                self.move(area.center() - self.rect().center())
            self.show()
        self.expiry.start(5000 if self.state is AssistantState.ERROR else timeout_ms)

    def dismiss(self):
        self.expiry.stop()
        self.surface.set_level(0)
        self.surface.set_suspended(True)
        self.hide()

    def set_level(self, level):
        self.surface.set_level(level)

    def set_reduced_motion(self, enabled):
        self.reduced_motion = bool(enabled)
        self.surface.set_reduced_motion(enabled)

    def showEvent(self, event):
        super().showEvent(event)
        self.surface.set_suspended(False)

    def closeEvent(self, event):
        self.dismiss()
        self.surface.dispose()
        super().closeEvent(event)


def create_visualizer():
    # The headless Qt plugin cannot create a native WebGL surface; native
    # integration checks separately exercise the actual dashboard and overlay.
    if QGuiApplication.platformName() in {"offscreen", "minimal"}:
        return Visualizer()
    return NeuralVisualizer()


def create_overlay():
    if QGuiApplication.platformName() in {"offscreen", "minimal"}:
        return BrainOverlay()
    return NeuralBrainOverlay()
