"""Audition local files without microphone acquisition or changing the active voice."""

import json
from pathlib import Path
import wave
import winsound

from PySide6.QtCore import Qt
from PySide6.QtMultimedia import QAudioFormat, QMediaDevices
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

from jarvis.voice.speech import SpeechOutput


class VoiceComparisonWindow(QMainWindow):
    def __init__(self, root: Path):
        super().__init__()
        self.root = root
        self.folder = root / "data/voice-comparison"
        self.manifest = json.loads((self.folder / "manifest.json").read_text(encoding="utf-8"))
        self.player = SpeechOutput(self)
        self.setWindowTitle("JARVIS · Confronto voci locali")
        self.resize(760, 530)
        self.setMinimumSize(650, 480)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)
        title = QLabel("J A R V I S  /  CONFRONTO VOCALE")
        title.setObjectName("brand")
        layout.addWidget(title)
        phrase = QLabel(self.manifest["phrase"])
        phrase.setTextFormat(Qt.TextFormat.PlainText)
        phrase.setWordWrap(True)
        layout.addWidget(phrase)
        form = QFormLayout()
        self.voices = QComboBox()
        for sample in self.manifest["samples"]:
            self.voices.addItem(sample["name"] + " · " + sample["gender"], sample)
        self.output = QComboBox()
        default = QMediaDevices.defaultAudioOutput()
        for device in QMediaDevices.audioOutputs():
            self.output.addItem(device.description(), bytes(device.id()).hex())
            if device.id() == default.id():
                self.output.setCurrentIndex(self.output.count() - 1)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(85)
        self.volume.setToolTip("Volume del solo player JARVIS. Il riferimento Windows usa il volume di sistema.")
        self.volume.valueChanged.connect(lambda value: self._volume(value))
        form.addRow("Voce da ascoltare", self.voices)
        form.addRow("Uscita JARVIS", self.output)
        form.addRow("Volume JARVIS", self.volume)
        layout.addLayout(form)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setObjectName("muted")
        layout.addWidget(self.details)
        buttons = QHBoxLayout()
        original = QPushButton("Originale · player Windows")
        original.clicked.connect(self.play_original)
        fixed = QPushButton("JARVIS · PCM corretto")
        fixed.clicked.connect(self.play_prepared)
        buttons.addWidget(original)
        buttons.addWidget(fixed)
        layout.addLayout(buttons)
        self.status = QLabel("Seleziona una voce e un percorso di riproduzione.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        layout.addStretch()
        note = QLabel("Solo ascolto: la voce attiva di JARVIS non viene cambiata.\n"
                      "Elsa è un riferimento femminile; sul PC è disponibile una sola voce italiana maschile, Cosimo.\n"
                      "Chatterbox e Kokoro non sono ancora installati. Il microfono non viene aperto da questa finestra.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        stop = QPushButton("■ STOP audio")
        stop.setObjectName("stopButton")
        stop.clicked.connect(self.stop)
        layout.addWidget(stop)
        self.voices.currentIndexChanged.connect(self._selection)
        self.output.currentIndexChanged.connect(self.stop)
        self.player.error.connect(self.status.setText)
        self.player.finished.connect(self._finished)
        self._selection()

    def _volume(self, value):
        self.player.volume = value / 100
        if self.player.sink:
            self.player.sink.setVolume(value / 100)

    def _selection(self):
        self.stop()
        item = self.voices.currentData()
        self.details.setText(f"Originale: {item['source_rate']} Hz · mono PCM16 · {item['duration_seconds']:.2f} s\n"
                             f"Campione preparato: 48000 Hz · stereo PCM16 · clipping: {item['prepared_clipped_samples']} campioni")

    def _path(self, key):
        path = (self.folder / self.voices.currentData()[key]).resolve()
        if not path.is_relative_to(self.folder.resolve()) or not path.is_file():
            raise ValueError("Campione locale non valido.")
        return path

    def play_original(self):
        self.stop()
        try:
            winsound.PlaySound(str(self._path("original")), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            self.status.setText("Riferimento Windows: riproduzione sull'uscita audio predefinita di sistema.")
        except (ValueError, RuntimeError):
            self.status.setText("Impossibile riprodurre il riferimento Windows.")

    def play_prepared(self):
        self.stop()
        try:
            with wave.open(str(self._path("prepared")), 'rb') as stream:
                if stream.getsampwidth() != 2:
                    raise ValueError
                fmt = QAudioFormat()
                fmt.setSampleRate(stream.getframerate())
                fmt.setChannelCount(stream.getnchannels())
                fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
                data = stream.readframes(stream.getnframes())
            self.player.output_device_id = self.output.currentData() or ""
            self.player.volume = self.volume.value() / 100
            self.status.setText("Riproduzione del campione tramite il percorso audio JARVIS…")
            self.player.play_pcm(data, fmt)
        except (ValueError, OSError, wave.Error):
            self.status.setText("Campione WAV non valido o non disponibile.")

    def _finished(self):
        if self.player.played_microseconds:
            self.status.setText(f"Audio elaborato: {self.player.played_microseconds / 1_000_000:.2f} s · {self.player.last_device_name}")

    def stop(self):
        winsound.PlaySound(None, 0)
        self.player.stop()

    def closeEvent(self, event):
        self.stop()
        event.accept()
