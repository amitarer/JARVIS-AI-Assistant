"""Standalone real-microphone test: custom wake word → overlay → local Windows voice.

No controller, SQLite, Ollama, STT model or cloud service is used by this window.
"""

import time
from dataclasses import replace

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QMainWindow, QProgressBar, QPushButton, QVBoxLayout, QWidget)
from PySide6.QtMultimedia import QMediaDevices

from jarvis.ui.overlay import BrainOverlay
from jarvis.voice.audio import AudioInput
from jarvis.voice.speech import SpeechOutput
from jarvis.voice.wake_word import WakeWorker

PHRASE = "Sono operativo. Dimmi pure"


class VoiceTestWindow(QMainWindow):
    def __init__(self, root, settings, *, auto_start: bool = True):
        super().__init__()
        self.root, self.settings = root, settings
        self.setWindowTitle("JARVIS · Test vocale locale · senza AI")
        self.resize(690, 570)
        self.setMinimumSize(620, 510)
        self.overlay = BrainOverlay()
        self.audio = AudioInput(self)
        self.speech = SpeechOutput(self)
        self.speech.allow_fallback = True
        self.speech.voice_name = settings.voice.voice_name
        self.worker = None
        self.closing = False
        self.manual_active = False
        self.enabled = False
        self.wanted = False
        self.triggered_at = None
        self.received_frames = 0
        self.detections = 0
        self.cycle_active = False
        self.last_pcm_bytes = 0
        self.max_output_level = 0.0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._end_cycle)
        self.shutdown_timer = QTimer(self)
        self.shutdown_timer.setInterval(50)
        self.shutdown_timer.timeout.connect(self._finish_shutdown)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(16)
        heading = QLabel("J A R V I S   /   VOICE TEST")
        heading.setObjectName("brand")
        layout.addWidget(heading)
        note = QLabel("Pronuncia soltanto «Jarvis». Il test usa il microfono reale e il modello ONNX personalizzato.\n"
                      "Non richiede un modello AI e non esegue operazioni Windows.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status_label = QLabel("MICROFONO OFF")
        self.status_label.setObjectName("stateLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status_label)
        form = QFormLayout()
        self.input_device = QComboBox()
        default = QMediaDevices.defaultAudioInput()
        for device in QMediaDevices.audioInputs():
            self.input_device.addItem(device.description(), bytes(device.id()).hex())
            if device.id() == default.id():
                self.input_device.setCurrentIndex(self.input_device.count() - 1)
        self.output_device = QComboBox()
        default = QMediaDevices.defaultAudioOutput()
        for device in QMediaDevices.audioOutputs():
            self.output_device.addItem(device.description(), bytes(device.id()).hex())
            if device.id() == default.id():
                self.output_device.setCurrentIndex(self.output_device.count() - 1)
        self.sensitivity = QDoubleSpinBox()
        self.sensitivity.setRange(0.10, 0.95)
        self.sensitivity.setSingleStep(0.05)
        self.sensitivity.setDecimals(2)
        self.sensitivity.setValue(settings.voice.sensitivity)
        form.addRow("Microfono", self.input_device)
        form.addRow("Altoparlanti / cuffie", self.output_device)
        form.addRow("Sensibilità (più alta = più sensibile)", self.sensitivity)
        layout.addLayout(form)
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setFixedHeight(8)
        layout.addWidget(self.meter)
        self.score_label = QLabel("Probabilità modello: —   |   Riconoscimenti vocali: 0")
        self.score_label.setObjectName("muted")
        layout.addWidget(self.score_label)
        self.audio_label = QLabel("Audio: in attesa di riproduzione.")
        self.audio_label.setWordWrap(True)
        self.audio_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.audio_label)
        layout.addStretch()
        buttons = QHBoxLayout()
        self.mic_button = QPushButton("Attiva microfono")
        self.mic_button.clicked.connect(self.toggle_microphone)
        self.manual_button = QPushButton("Prova manuale overlay + voce")
        self.manual_button.clicked.connect(lambda: self.activate(manual=True))
        buttons.addWidget(self.mic_button)
        buttons.addWidget(self.manual_button)
        layout.addLayout(buttons)
        self.stop_button = QPushButton("■ STOP · microfono e audio")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.clicked.connect(self.stop)
        layout.addWidget(self.stop_button)

        self.audio.frames.connect(self._frames)
        self.audio.level.connect(lambda value: self.meter.setValue(int(value * 100)))
        self.audio.error.connect(self._error)
        self.speech.started.connect(self._speech_started)
        self.speech.level.connect(self._output_level)
        self.speech.finished.connect(self._speech_finished)
        self.speech.error.connect(self._speech_error)
        self.speech.pcm_ready.connect(self._pcm_ready)
        self.input_device.currentIndexChanged.connect(self._configuration_changed)
        self.sensitivity.valueChanged.connect(self._configuration_changed)
        if auto_start:
            QTimer.singleShot(200, self.start_microphone)

    def _configuration_changed(self):
        was_enabled = self.wanted
        self.stop_microphone()
        if was_enabled:
            QTimer.singleShot(200, self.start_microphone)

    def toggle_microphone(self):
        if self.wanted:
            self.stop_microphone()
        else:
            self.start_microphone()

    def start_microphone(self):
        if self.closing or self.cycle_active:
            return
        self.wanted = True
        if self.worker is not None:
            if self.worker.isRunning():
                if self.worker.stopping.is_set():
                    QTimer.singleShot(100, self.start_microphone)
                return
            self._worker_finished()
        self.status_label.setText("Caricamento openWakeWord locale…")
        self.mic_button.setText("Disattiva microfono")
        voice = replace(self.settings.voice, sensitivity=self.sensitivity.value(),
                        microphone_id=self.input_device.currentData() or "")
        self.worker = WakeWorker(self.root, voice, self)
        self.worker.ready.connect(self._ready)
        self.worker.detected.connect(self._detected)
        self.worker.score.connect(self._score)
        self.worker.error.connect(self._error)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _ready(self):
        if not self.wanted or self.closing or self.worker is None:
            return
        try:
            self.audio.start(self.input_device.currentData() or "")
        except Exception as exc:
            self._error(str(exc))
            return
        self.enabled = True
        self.status_label.setText("MICROFONO ON · pronuncia «Jarvis»")

    def _frames(self, samples):
        self.received_frames += len(samples)
        if self.enabled and self.worker and not self.cycle_active:
            self.worker.feed(samples)

    def _score(self, score):
        self.score_label.setText(f"Probabilità modello: {score:.3f}   |   Riconoscimenti vocali: {self.detections}")

    def _detected(self, score):
        if self.enabled and not self.cycle_active:
            self.detections += 1
            self._score(score)
            self.activate(manual=False)

    def activate(self, manual: bool = False):
        if self.closing or self.cycle_active:
            return
        self.manual_active = manual
        self.cycle_active = True
        self.triggered_at = time.monotonic()
        if self.worker:
            self.worker.suspended.set()
            self.worker.flush()
        self.audio.stop()
        self.enabled = False
        self.manual_button.setEnabled(False)
        self.status_label.setText("ATTIVAZIONE MANUALE · nessun rilevamento conteggiato" if manual
                                  else "«JARVIS» RICONOSCIUTO · microfono in pausa durante la risposta")
        self.overlay.present("listening", PHRASE, preview=manual, timeout_ms=5000)
        self.timer.start(5000)
        self.speech.output_device_id = self.output_device.currentData() or ""
        self.max_output_level = 0.0
        self.speech.speak(PHRASE)

    def _speech_started(self):
        self.overlay.present("speaking", PHRASE, preview=self.manual_active,
                             timeout_ms=max(1, int(5000 - (time.monotonic() - self.triggered_at) * 1000)))

    def _output_level(self, level):
        self.max_output_level = max(self.max_output_level, level)
        self.overlay.set_level(level)

    def _pcm_ready(self, data, fmt):
        self.last_pcm_bytes = len(data)
        self.audio_label.setText(f"Audio PCM locale: {len(data):,} byte · {fmt.sampleRate()} Hz")

    def _speech_finished(self):
        if self.speech.played_microseconds > 0:
            self.audio_label.setText(f"Audio inviato a: {self.speech.last_device_name}\n"
                                     f"Riprodotti {self.speech.played_microseconds / 1_000_000:.2f} s. Conferma di sentirlo dagli altoparlanti.")

    def _speech_error(self, message):
        self.audio_label.setText(message + " Il test overlay resta disponibile.")

    def _end_cycle(self):
        self.speech.stop()
        self.overlay.dismiss()
        self.cycle_active = False
        self.manual_button.setEnabled(True)
        if self.wanted and not self.closing:
            # Capture is physically stopped during playback, then restarted after
            # a short echo tail. No output audio reaches the wake detector.
            QTimer.singleShot(500, self._resume)

    def _resume(self):
        if not self.wanted or self.closing or self.cycle_active:
            return
        if self.worker and self.worker.isRunning() and not self.worker.stopping.is_set():
            self.worker.flush()
            self.worker.suspended.clear()
            self._ready()
        else:
            self.start_microphone()

    def stop_microphone(self):
        self.wanted = self.enabled = False
        self.audio.stop()
        if self.worker:
            self.worker.stop()
        self.mic_button.setText("Attiva microfono")
        self.status_label.setText("MICROFONO OFF · acquisizione arrestata")

    def _worker_finished(self):
        if self.worker is not None and not self.worker.isRunning():
            self.worker.deleteLater()
            self.worker = None

    def _error(self, message):
        self.stop_microphone()
        self.status_label.setText(message)

    def stop(self):
        self.stop_microphone()
        self.timer.stop()
        self.speech.stop()
        self.overlay.dismiss()
        self.cycle_active = False
        self.manual_button.setEnabled(True)

    def closeEvent(self, event):
        if (self.worker is not None and self.worker.isRunning()) or not self.speech.is_stopped():
            event.ignore()
            self.closing = True
            self.stop()
            self.shutdown_timer.start()
        else:
            self.closing = True
            self.stop()
            self.overlay.close()
            event.accept()

    def _finish_shutdown(self):
        if (self.worker is None or not self.worker.isRunning()) and self.speech.is_stopped():
            self.shutdown_timer.stop()
            self.close()
