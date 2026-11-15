"""Isolated neural preview. Never constructs the assistant, audio, DB or tools."""

import json
import math
from pathlib import Path

from PySide6.QtCore import QEvent, QEasingCurve, QPropertyAnimation, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton,
    QSlider, QSpinBox, QVBoxLayout, QWidget,
)
from PySide6.QtWebEngineCore import (
    QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from jarvis.ui.neural_geometry import NeuralGraph, build_neural_graph
from jarvis.ui.neural_organic import build_organic_graph


ASSETS = Path(__file__).with_name("neural").resolve()
STATES = {
    "activating": ("Attivazione", "La rete prende vita, dal centro ai filamenti esterni."),
    "listening": ("Ascolto", "Ampiezza manuale per provare la risposta del cervello."),
    "thinking": ("Elaborazione", "Impulsi luminosi si propagano attraverso le sinapsi."),
    "speaking": ("Voce", "Ampiezza manuale per provare la risposta al parlato."),
    "executing": ("Esecuzione", "Overlay nascosto e rendering sospeso. Nessuna azione Windows eseguita."),
    "confirmation": ("Conferma", "Simulazione grafica. Le autorizzazioni reali restano nell’interfaccia attuale."),
    "error": ("Errore", "Simulazione: il servizio non risponde. Nessun errore reale provocato."),
    "idle": ("Riposo", "Rete sospesa. Seleziona uno stato per riattivarla."),
}


class LocalAssetsOnly(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        url = info.requestUrl()
        allowed = url.scheme() == "file" and Path(url.toLocalFile()).resolve() in {
            ASSETS / "index.html", ASSETS / "neural.css", ASSETS / "neural.js",
        }
        info.block(not allowed)


class NeuralPage(QWebEnginePage):
    console_error = Signal(str)

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        return url == QUrl.fromLocalFile(str(ASSETS / "index.html"))

    def createWindow(self, window_type):
        return None

    def javaScriptConsoleMessage(self, level, message, line, source):
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            self.console_error.emit(f"JavaScript {line}: {message[:500]}")


class NeuralView(QWebEngineView):
    ready = Signal()
    failed = Signal(str)

    def __init__(self, graph: NeuralGraph, *, pixel_ratio=1.5, fps=60, render_idle=False, parent=None):
        super().__init__(parent)
        self.graph, self.pixel_ratio, self.fps = graph, pixel_ratio, fps
        self.render_idle = render_idle
        self.initialized = False
        self.disposed = False
        self.state = "thinking"
        self.level = 0.0
        self.rotation = True
        self.reduced_motion = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent; border: none;")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.profile = QWebEngineProfile(self)  # off the record: no persistent browser data
        self.interceptor = LocalAssetsOnly(self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.profile.downloadRequested.connect(lambda download: download.cancel())
        page = NeuralPage(self.profile, self)
        self.setPage(page)
        page.setBackgroundColor(QColor(0, 0, 0, 0))
        page.console_error.connect(self.failed)
        page.renderProcessTerminated.connect(lambda *_: self.failed.emit("Processo WebGL terminato. Riapri l’anteprima."))
        page.permissionRequested.connect(lambda permission: permission.deny())
        settings = page.settings()
        for name in ("LocalContentCanAccessRemoteUrls", "JavascriptCanOpenWindows",
                     "JavascriptCanAccessClipboard", "JavascriptCanPaste", "LocalStorageEnabled",
                     "PluginsEnabled", "FullScreenSupportEnabled", "ScreenCaptureEnabled",
                     "DnsPrefetchEnabled", "NavigateOnDropEnabled", "AllowWindowActivationFromJavaScript"):
            settings.setAttribute(getattr(QWebEngineSettings.WebAttribute, name), False)
        # Only the three exact asset paths pass the request interceptor above.
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        self.loadFinished.connect(self._loaded)
        self.load(QUrl.fromLocalFile(str(ASSETS / "index.html")))

    def _loaded(self, success):
        if self.disposed:
            return
        if not success:
            self.failed.emit("Impossibile caricare gli asset locali del renderer.")
            return
        payload = json.dumps(self.graph.payload(), separators=(",", ":"), allow_nan=False)
        options = json.dumps({"pixelRatio": self.pixel_ratio, "fps": self.fps, "renderIdle": self.render_idle})
        self.page().runJavaScript(f"window.neural && window.neural.initialize({payload},{options})", self._initialized)

    def _initialized(self, success):
        if self.disposed:
            return
        self.initialized = success is True
        if not self.initialized:
            self.failed.emit("WebGL non inizializzato: controlla il messaggio del renderer.")
            return
        self.set_state(self.state)
        self.set_rotation(self.rotation)
        self.set_reduced_motion(self.reduced_motion)
        self.ready.emit()

    def _call(self, method: str, value):
        # Only internal method names below; serialized values cannot become JS source.
        if self.initialized and not self.disposed:
            self.page().runJavaScript(f"window.neural.{method}({json.dumps(value, allow_nan=False)})")

    def set_state(self, state: str):
        if state not in STATES:
            raise ValueError("Stato grafico sconosciuto.")
        self.state = state
        self.level = 0
        self._call("setState", state)
        self._call("setVisible", self.isVisible() and not self.window().isMinimized())

    def set_level(self, level: float):
        if isinstance(level, bool) or not isinstance(level, (int, float)) or not math.isfinite(level):
            raise ValueError("Ampiezza non finita.")
        self.level = max(0.0, min(1.0, level))
        self._call("setAudioLevel", self.level)

    def set_rotation(self, enabled):
        self.rotation = bool(enabled)
        self._call("setRotation", self.rotation)

    def set_reduced_motion(self, enabled):
        self.reduced_motion = bool(enabled)
        self._call("setReducedMotion", self.reduced_motion)

    def snapshot(self, callback):
        if not self.initialized or self.disposed:
            callback({"ready": False, "state": self.state})
            return
        def receive(value):
            if self.disposed:
                return
            try:
                callback(json.loads(value) if isinstance(value, str) else {})
            except (ValueError, TypeError):
                callback({})
        self.page().runJavaScript("JSON.stringify(window.neural.snapshot())", receive)

    def suspend(self):
        self._call("setVisible", False)

    def resume(self):
        self._call("setVisible", self.isVisible() and not self.window().isMinimized())

    def showEvent(self, event):
        super().showEvent(event)
        self.resume()

    def hideEvent(self, event):
        self.suspend()
        super().hideEvent(event)

    def dispose(self):
        if not self.disposed:
            self._call("dispose", None)
            self.disposed = True
            self.initialized = False


class NeuralPreviewOverlay(QWidget):
    """Experimental transparent surface, isolated from BrainOverlay and its barrier."""

    def __init__(self, graph, *, pixel_ratio=1.5, fps=60):
        flags = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                 Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus |
                 Qt.WindowType.WindowTransparentForInput)
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setWindowTitle("JARVIS · Simulazione overlay neurale")
        self.resize(680, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = NeuralView(graph, pixel_ratio=pixel_ratio, fps=fps, parent=self)
        self.view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self.view, 1)
        label = QLabel("ANTEPRIMA · SIMULAZIONE GRAFICA")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #a6d9e8; background: transparent; font: 11px 'Consolas'; padding: 10px;")
        layout.addWidget(label)
        self.expiry = QTimer(self)
        self.expiry.setSingleShot(True)
        self.expiry.timeout.connect(self.fade_out)
        self.fade = QPropertyAnimation(self, b"windowOpacity", self)
        self.fade.setDuration(220)
        self.fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.fade.finished.connect(self._faded)

    def present(self, state, screen=None):
        if state in {"idle", "executing"}:
            self.dismiss()
            return
        self.fade.stop()
        screen = screen or QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self.resize(min(680, area.width()), min(560, area.height()))
            self.move(area.center() - self.rect().center())
        self.view.set_state(state)
        self.setWindowOpacity(0)
        self.show()
        self.view.resume()
        self.fade.setStartValue(0.0)
        self.fade.setEndValue(1.0)
        self.fade.start()
        self.expiry.start(12000)

    def fade_out(self):
        self.fade.stop()
        self.fade.setStartValue(self.windowOpacity())
        self.fade.setEndValue(0.0)
        self.fade.start()

    def _faded(self):
        if self.windowOpacity() < 0.01:
            self.dismiss()

    def dismiss(self):
        # Immediate path for executing/idle; a fade must never delay desktop access.
        self.fade.stop()
        self.expiry.stop()
        self.view.suspend()
        self.hide()

    def hideEvent(self, event):
        self.view.suspend()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.dismiss()
        self.view.dispose()
        super().closeEvent(event)


STYLE = """
QWidget#NeuralPreview { background: #03070d; color: #deedf6; }
QLabel { background: transparent; color: #d8e9f3; }
QLabel#Brand { font: 300 25px 'Segoe UI'; letter-spacing: 9px; color: #effaff; }
QLabel#Eyebrow { font: 11px 'Consolas'; color: #6391a6; }
QLabel#StateTitle { font: 300 26px 'Segoe UI'; color: #dbf5ff; }
QLabel#Description { font: 13px 'Segoe UI'; color: #7e9bab; }
QLabel#Simulation { font: 10px 'Consolas'; color: #78bdd1; }
QPushButton { background: transparent; color: #8ba9b9; padding: 9px 11px;
              border: 0; border-bottom: 1px solid #18303e; font: 12px 'Segoe UI'; }
QPushButton:hover { color: #defaff; border-bottom-color: #5bb9d6; }
QPushButton:checked { color: #c5f7ff; border-bottom: 2px solid #63cce6; }
QPushButton:disabled { color: #405461; }
QCheckBox { color: #8ba9b9; font: 12px 'Segoe UI'; spacing: 8px; }
QComboBox { background: #09121c; color: #9dbccc; border: 1px solid #18303e; padding: 5px; }
QComboBox QAbstractItemView { background: #09121c; color: #b1dce8; }
QSlider::groove:horizontal { background: #18303e; height: 2px; }
QSlider::handle:horizontal { background: #a1e6f4; width: 10px; margin: -4px 0; border-radius: 5px; }
"""


class NeuralPreviewWindow(QWidget):
    def __init__(self, *, particles=4800, pixel_ratio=1.5, fps=60, style="organic"):
        super().__init__()
        self.setObjectName("NeuralPreview")
        self.setWindowTitle("JARVIS · Anteprima neurale 3D · Simulazione grafica")
        self.resize(1180, 940)
        self.setMinimumSize(1000, 800)
        if style not in {"organic", "cortex"}:
            raise ValueError("Stile neurale sconosciuto.")
        self.style = style
        theme = STYLE
        if style == "organic":
            for cold, warm in {"#03070d": "#070605", "#deedf6": "#f2e6d2", "#d8e9f3": "#e6d6bb",
                               "#effaff": "#fff4de", "#6391a6": "#a48a61", "#dbf5ff": "#ffe9be",
                               "#7e9bab": "#a39680", "#78bdd1": "#c7a56a", "#8ba9b9": "#b9a68a",
                               "#18303e": "#3c3020", "#defaff": "#fff1d2", "#5bb9d6": "#d5ae65",
                               "#c5f7ff": "#ffe4b1", "#63cce6": "#e9be73", "#09121c": "#15110b",
                               "#a1e6f4": "#f4d29d"}.items():
                theme = theme.replace(cold, warm)
        self.setStyleSheet(theme)
        self.state = "thinking"
        self.sequence_index = 0
        self.selected_neuron = -2
        self.graph = build_organic_graph(particles) if style == "organic" else build_neural_graph(particles)
        self.clean_view = False
        self.sample_player = None
        self.sample_playing = False
        self.overlay = NeuralPreviewOverlay(self.graph, pixel_ratio=pixel_ratio, fps=fps)
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 24, 36, 22)
        root.setSpacing(10)
        header = QHBoxLayout()
        brand = QLabel("JARVIS")
        brand.setObjectName("Brand")
        header.addWidget(brand)
        header.addStretch()
        eyebrow = QLabel("ORGANIC NEURAL CORE / AMBER 02" if style == "organic" else "NEURAL INTELLIGENCE / CORTEX 01")
        eyebrow.setObjectName("Eyebrow")
        header.addWidget(eyebrow)
        root.addLayout(header)
        self.view = NeuralView(self.graph, pixel_ratio=pixel_ratio, fps=fps, parent=self)
        root.addWidget(self.view, 1)
        self.title = QLabel()
        self.title.setObjectName("StateTitle")
        self.description = QLabel()
        self.description.setObjectName("Description")
        self.description.setWordWrap(True)
        root.addWidget(self.title)
        root.addWidget(self.description)
        state_row = QHBoxLayout()
        state_row.setSpacing(4)
        self.buttons = {}
        for state, (label, _) in STATES.items():
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, state=state: self.select_state(state, manual=True))
            state_row.addWidget(button)
            self.buttons[state] = button
        root.addLayout(state_row)
        audio_row = QHBoxLayout()
        audio_label = QLabel("AMPIEZZA MANUALE · SIMULAZIONE")
        self.audio_label = audio_label
        audio_label.setObjectName("Simulation")
        audio_row.addWidget(audio_label)
        self.amplitude = QSlider(Qt.Orientation.Horizontal)
        self.amplitude.setRange(0, 100)
        self.amplitude.setAccessibleName("Ampiezza simulata, nessun microfono attivo")
        self.amplitude.valueChanged.connect(self._send_level)
        audio_row.addWidget(self.amplitude, 1)
        self.rotation = QCheckBox("Rotazione")
        self.rotation.setChecked(True)
        self.rotation.toggled.connect(self._rotation)
        audio_row.addWidget(self.rotation)
        self.reduced = QCheckBox("Movimento ridotto")
        self.reduced.toggled.connect(self._reduced)
        audio_row.addWidget(self.reduced)
        root.addLayout(audio_row)
        navigation = QHBoxLayout()
        zoom_label = QLabel("ZOOM")
        zoom_label.setObjectName("Simulation")
        navigation.addWidget(zoom_label)
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(50, 600)
        self.zoom.setValue(100)
        self.zoom.setAccessibleName("Zoom neurale da 0,5 a 6 volte")
        self.zoom.valueChanged.connect(lambda value: self.view._call("setZoom", value / 100))
        navigation.addWidget(self.zoom, 1)
        self.zoom_label = QLabel("1.00×")
        navigation.addWidget(self.zoom_label)
        navigation.addSpacing(20)
        navigation.addWidget(QLabel("Neurone"))
        self.neuron_id = QSpinBox()
        self.neuron_id.setRange(0, particles - 1)
        self.neuron_id.setPrefix("N-")
        self.neuron_id.setStyleSheet("background: #09121c; color: #c5e8f4; padding: 4px; border: 1px solid #18303e;")
        navigation.addWidget(self.neuron_id)
        inspect = QPushButton("Ispeziona")
        inspect.clicked.connect(lambda: self.view._call("selectNeuron", self.neuron_id.value()))
        navigation.addWidget(inspect)
        focus = QPushButton("Centra")
        focus.clicked.connect(lambda: self.view.page().runJavaScript("window.neural?.focusNeuron()"))
        navigation.addWidget(focus)
        clear = QPushButton("Deseleziona")
        clear.clicked.connect(lambda: self.view._call("selectNeuron", -1))
        navigation.addWidget(clear)
        root.addLayout(navigation)
        self.inspector = QLabel("Clicca un neurone per ispezionare coordinate e connessioni della rete grafica.")
        self.inspector.setObjectName("Description")
        self.inspector.setWordWrap(True)
        self.inspector.setMinimumHeight(52)
        self.inspector.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.inspector)
        actions = QHBoxLayout()
        self.sequence = QPushButton("Sequenza simulata")
        self.sequence.setCheckable(True)
        self.sequence.toggled.connect(self._sequence_toggled)
        actions.addWidget(self.sequence)
        reset = QPushButton("Ripristina vista")
        reset.clicked.connect(lambda: self.view.page().runJavaScript("window.neural?.resetView()"))
        actions.addWidget(reset)
        clean = QPushButton("Solo nucleo · Tab")
        clean.clicked.connect(self.toggle_clean_view)
        actions.addWidget(clean)
        self.sample_button = QPushButton("Ascolta Cosimo · PCM reale")
        self.sample_button.clicked.connect(lambda: self.play_sample())
        actions.addWidget(self.sample_button)
        actions.addStretch()
        self.screens = QComboBox()
        for screen in QGuiApplication.screens():
            self.screens.addItem(screen.name(), screen)
        actions.addWidget(self.screens)
        self.overlay_button = QPushButton("Prova overlay · 12 s")
        self.overlay_button.clicked.connect(self._show_overlay)
        actions.addWidget(self.overlay_button)
        close_overlay = QPushButton("Nascondi overlay")
        close_overlay.clicked.connect(self.overlay.fade_out)
        actions.addWidget(close_overlay)
        root.addLayout(actions)
        footer = QHBoxLayout()
        note = QLabel("ANTEPRIMA · Nessun microfono o AI / Clic: ispeziona · Trascina: ruota · Shift+trascina: sposta")
        note.setObjectName("Simulation")
        footer.addWidget(note)
        footer.addStretch()
        self.metrics = QLabel("Inizializzazione WebGL…")
        self.metrics.setObjectName("Eyebrow")
        footer.addWidget(self.metrics)
        root.addLayout(footer)
        self.telemetry = QTimer(self)
        self.telemetry.setInterval(200)
        self.telemetry.timeout.connect(lambda: self.view.snapshot(self._metrics))
        self.sequence_timer = QTimer(self)
        self.sequence_timer.setInterval(4200)
        self.sequence_timer.timeout.connect(self._next_state)
        self.audio_timer = QTimer(self)
        self.audio_timer.setInterval(40)
        self.audio_timer.timeout.connect(self._send_level)
        self.view.ready.connect(self._ready)
        self.view.failed.connect(self._failed)
        self.overlay.view.failed.connect(self._failed)
        self.escape = QShortcut(QKeySequence("Escape"), self)
        self.escape.activated.connect(self.stop)
        self.clean_shortcut = QShortcut(QKeySequence("Tab"), self)
        self.clean_shortcut.activated.connect(self.toggle_clean_view)
        self.select_state("thinking")

    def _ready(self):
        self.select_state(self.state)
        self.telemetry.start()

    def _failed(self, message):
        self.description.setText(message)
        self.metrics.setText("Renderer non disponibile")

    def _metrics(self, stats):
        if stats.get("error"):
            self._failed(stats["error"])
        elif stats.get("ready"):
            self.metrics.setText(f"{stats.get('fps', 0):.0f} FPS · {stats.get('neurons', 0)} neuroni · DPR {stats.get('pixelRatio', 0):.2f}"
                                 if stats.get("running") else "Rendering sospeso")
            zoom = stats.get("zoom", 1)
            self.zoom.blockSignals(True)
            self.zoom.setValue(round(zoom * 100))
            self.zoom.blockSignals(False)
            self.zoom_label.setText(f"{zoom:.2f}×")
            self.rotation.setChecked(stats.get("rotation", True))
            selected = stats.get("selected", -1)
            if selected != self.selected_neuron:
                self.selected_neuron = selected
                self._inspect(selected)

    def _inspect(self, index):
        if not isinstance(index, int) or not 0 <= index < len(self.graph.positions):
            self.inspector.setText("Clicca un neurone per ispezionare coordinate e connessioni della rete grafica. "
                                   "Zoom fino a 6×; Shift+trascina per esplorare i dettagli.")
            return
        self.neuron_id.setValue(index)
        point = self.graph.positions[index]
        side = "sinistro" if self.graph.hemispheres[index] < 0 else "destro"
        region = ("Settore geometrico" if self.style == "organic" else "Emisfero") + f" {side}"
        neighbors = sorted(b if a == index else a for a, b in self.graph.edges if index in (a, b))
        ids = ", ".join(f"N-{neighbor:04d}" for neighbor in neighbors)
        self.inspector.setText(
            f"N-{index:04d} · {region} · {len(neighbors)} sinapsi · "
            f"Coordinate modello: x {point[0]:+.3f}, y {point[1]:+.3f}, z {point[2]:+.3f}\n"
            f"Collegato a: {ids or 'nessun vicino'}. Dati del prototipo procedurale, senza corrispondenza ai neuroni di Qwen."
        )

    def toggle_clean_view(self):
        self.clean_view = not self.clean_view
        def visit(layout):
            for i in range(layout.count()):
                item = layout.itemAt(i)
                widget = item.widget()
                if widget is not None and widget is not self.view:
                    widget.setVisible(not self.clean_view)
                elif item.layout() is not None:
                    visit(item.layout())
        visit(self.layout())

    def select_state(self, state, *, manual=False):
        self._stop_sample()
        if manual:
            self.sequence.setChecked(False)
        self.state = state
        title, description = STATES[state]
        self.title.setText(title)
        self.description.setText(description)
        for key, button in self.buttons.items():
            button.setChecked(key == state)
        self.amplitude.setValue(0)
        self.amplitude.setEnabled(state in {"listening", "speaking"})
        self.view.set_state(state)
        self.overlay.view.set_state(state)
        if state in {"idle", "executing"}:
            self.overlay.dismiss()
            self.audio_timer.stop()
        elif self.isVisible() and state in {"listening", "speaking"}:
            self.audio_timer.start()
        else:
            self.audio_timer.stop()

    def _send_level(self, *_):
        level = self.amplitude.value() / 100
        self.view.set_level(level)
        if self.overlay.isVisible():
            self.overlay.view.set_level(level)

    def play_sample(self, *, volume=0.85):
        """Actual local PCM playback, independently of synthesis or assistant state."""
        import wave
        from PySide6.QtMultimedia import QAudioFormat
        from jarvis.voice.speech import SpeechOutput

        path = Path(__file__).resolve().parents[2] / "data/voice-reference/cosimo_neutro.wav"
        try:
            with wave.open(str(path), "rb") as wav:
                if wav.getsampwidth() != 2:
                    raise ValueError("Il campione deve essere PCM16.")
                fmt = QAudioFormat()
                fmt.setSampleRate(wav.getframerate())
                fmt.setChannelCount(wav.getnchannels())
                fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
                data = wav.readframes(wav.getnframes())
        except (OSError, ValueError, wave.Error):
            self.description.setText("Campione locale assente. Generarlo con scripts/prepare_reference_voice.py.")
            return
        self.select_state("speaking", manual=True)
        self.audio_timer.stop()
        self.amplitude.setEnabled(False)
        if self.sample_player is None:
            self.sample_player = SpeechOutput(self)
            self.sample_player.level.connect(self._sample_level)
            self.sample_player.finished.connect(self._sample_finished)
            self.sample_player.error.connect(self._sample_error)
        self.sample_playing = True
        self.sample_player.volume = max(0.0, min(1.0, volume))
        self.audio_label.setText("AMPIEZZA PCM REALE · CAMPIONE LOCALE")
        self.description.setText("Campione locale Microsoft Cosimo. Il nucleo segue l’ampiezza PCM del player; nessuna risposta AI generata.")
        self.sample_player.play_pcm(data, fmt)

    def _sample_level(self, level):
        if self.sample_playing:
            self.view.set_level(level)
            if self.overlay.isVisible():
                self.overlay.view.set_level(level)

    def _sample_finished(self):
        if self.sample_playing:
            self.sample_playing = False
            self.audio_label.setText("AMPIEZZA MANUALE · SIMULAZIONE")
            self.select_state("thinking")
            self.description.setText("Campione terminato. La voce attiva dell’assistente non è stata modificata.")

    def _sample_error(self, message):
        self._stop_sample()
        self.select_state("error")
        self.description.setText("Riproduzione del campione non riuscita: " + message)

    def _stop_sample(self):
        if self.sample_playing:
            self.sample_playing = False
            self.sample_player.stop()
            self.audio_label.setText("AMPIEZZA MANUALE · SIMULAZIONE")

    def _rotation(self, enabled):
        self.view.set_rotation(enabled)
        self.overlay.view.set_rotation(enabled)

    def _reduced(self, enabled):
        self.view.set_reduced_motion(enabled)
        self.overlay.view.set_reduced_motion(enabled)

    def _show_overlay(self):
        self.overlay.present(self.state, self.screens.currentData())

    def _sequence_toggled(self, enabled):
        if enabled:
            self.sequence_index = 0
            self.select_state("activating")
            self.sequence_timer.start()
        else:
            self.sequence_timer.stop()

    def _next_state(self):
        states = ["activating", "listening", "thinking", "speaking", "executing", "confirmation", "error", "idle"]
        self.sequence_index += 1
        if self.sequence_index >= len(states):
            self.sequence.setChecked(False)
        else:
            self.select_state(states[self.sequence_index])

    def stop(self):
        if self.clean_view:
            self.toggle_clean_view()
        self.sequence.setChecked(False)
        self.select_state("idle")

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMinimized():
                self._suspend()
            else:
                self.view.resume()
                self.telemetry.start()
                if self.state in {"listening", "speaking"}:
                    self.audio_timer.start()

    def _suspend(self):
        self._stop_sample()
        self.view.suspend()
        self.audio_timer.stop()
        self.telemetry.stop()
        self.sequence.setChecked(False)

    def hideEvent(self, event):
        self._suspend()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.view.resume()
        if self.view.initialized:
            self.telemetry.start()
        if self.state in {"listening", "speaking"}:
            self.audio_timer.start()

    def closeEvent(self, event):
        self._suspend()
        self.overlay.close()
        self.view.dispose()
        super().closeEvent(event)


def run_preview(*, particles=4800, pixel_ratio=1.5, fps=60, style="organic") -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("JARVIS Neural Preview")
    window = NeuralPreviewWindow(particles=particles, pixel_ratio=pixel_ratio, fps=fps, style=style)
    window.show()
    result = app.exec()
    # QWebEnginePage must be destroyed before its profile.
    from shiboken6 import delete
    delete(window.overlay.view.page())
    delete(window.view.page())
    return result
