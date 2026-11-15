"""Settings, activity inspection and explicit nonmodal approvals."""

import json

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QSpinBox,
                               QFormLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout)
from PySide6.QtMultimedia import QMediaDevices

from jarvis.core.models import ApprovalRequest


class ApprovalDialog(QDialog):
    decision = Signal(str, bool)

    def __init__(self, request: ApprovalRequest, timeout: int, parent=None):
        super().__init__(parent)
        self.request = request
        self._resolved = False
        self.setWindowTitle("Autorizzazione richiesta")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(540, 350)
        layout = QVBoxLayout(self)
        heading = QLabel("CONFERMA OPERAZIONE · RISCHIO " + request.risk.value.upper())
        heading.setObjectName("warning")
        layout.addWidget(heading)
        description = QLabel(request.description)
        description.setWordWrap(True)
        description.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(description)
        params = QTextEdit()
        params.setReadOnly(True)
        params.setPlainText(f"Strumento: {request.call.name}\nParametri: "
                            + json.dumps(json.loads(request.call.arguments_json), indent=2, ensure_ascii=False))
        layout.addWidget(params)
        layout.addWidget(QLabel(f"Scade dopo {timeout} secondi. STOP resta disponibile nella finestra principale."))
        buttons = QDialogButtonBox()
        deny = buttons.addButton("Nega", QDialogButtonBox.ButtonRole.RejectRole)
        approve = buttons.addButton("Approva questa azione", QDialogButtonBox.ButtonRole.AcceptRole)
        deny.setDefault(True)
        approve.setAutoDefault(False)
        deny.clicked.connect(self.reject)
        approve.clicked.connect(self.accept)
        layout.addWidget(buttons)
        self.expiry = QTimer(self)
        self.expiry.setSingleShot(True)
        self.expiry.timeout.connect(self.reject)
        self.expiry.start(timeout * 1000)

    def done(self, result: int) -> None:
        if not self._resolved:
            self._resolved = True
            self.expiry.stop()
            self.decision.emit(self.request.request_id, result == QDialog.DialogCode.Accepted)
        super().done(result)


class SettingsDialog(QDialog):
    reset_requested = Signal()

    def __init__(self, reduced_motion: bool, log_level: str, parent=None, *, settings=None, voice=None, voices=()):
        super().__init__(parent)
        self.setWindowTitle("Impostazioni JARVIS")
        self.resize(490, 350)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.motion = QCheckBox("Riduci le animazioni")
        self.motion.setChecked(reduced_motion)
        self.level = QComboBox()
        self.level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.level.setCurrentText(log_level)
        form.addRow("Interfaccia", self.motion)
        form.addRow("Log tecnici", self.level)
        provider = f"Ollama · {settings.ollama.model}\n{settings.ollama.url}" if settings and settings.ollama.enabled else "Modalità demo · nessun provider"
        form.addRow("Provider AI", QLabel(provider))
        form.addRow("Thinking", QLabel("Disattivazione richiesta; ragionamento escluso da voce e memoria"))
        self.microphone = QComboBox()
        self.microphone.addItem("Predefinito Windows", "")
        for device in QMediaDevices.audioInputs():
            self.microphone.addItem(device.description(), bytes(device.id()).hex())
        self.voice = QComboBox()
        self.voice.addItems(list(voices) or ["Microsoft Cosimo"])
        self.sensitivity = QDoubleSpinBox()
        self.sensitivity.setRange(0.1, 0.95)
        self.sensitivity.setSingleStep(0.05)
        self.conversation = QSpinBox()
        self.conversation.setRange(5, 120)
        self.conversation.setSuffix(" secondi")
        self.continuous = QCheckBox("Ascolta domande successive senza ripetere «Jarvis»")
        if voice:
            index = self.microphone.findData(voice.microphone_id)
            self.microphone.setCurrentIndex(max(0, index))
            self.voice.setCurrentText(voice.voice_name)
            self.sensitivity.setValue(voice.sensitivity)
            self.conversation.setValue(voice.conversation_seconds)
            self.continuous.setChecked(voice.continuous_conversation)
        form.addRow("Microfono", self.microphone)
        form.addRow("Voce italiana maschile", self.voice)
        form.addRow("Sensibilità «Jarvis»", self.sensitivity)
        form.addRow("Conversazione continua", self.conversation)
        form.addRow("Dopo la risposta", self.continuous)
        form.addRow("Agente", QLabel("Recupero letture · ricerche adattive e PDF · arresto con STOP"))
        layout.addLayout(form)
        privacy = QLabel("I messaggi sono salvati in data/jarvis.sqlite3, senza cifratura.\n"
                         "Non inserire password o token nella chat. I log tecnici non includono il testo dei messaggi.")
        privacy.setWordWrap(True)
        layout.addWidget(privacy)
        reset = QPushButton("Ripristina preferenze…")
        reset.clicked.connect(self._reset)
        layout.addWidget(reset)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _reset(self) -> None:
        self.reject()
        self.reset_requested.emit()


class ActivityDialog(QDialog):
    def __init__(self, tasks: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cronologia attività · ultime 50")
        self.resize(650, 420)
        layout = QVBoxLayout(self)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.set_tasks(tasks)
        layout.addWidget(self.text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_tasks(self, tasks: list[dict]) -> None:
        self.text.setPlainText("\n\n".join(
            f"{task['created_at']}\n{task['kind']}  ·  {task['status']}\nID: {task['id']}" for task in tasks
        ) or "Nessuna attività registrata.")
