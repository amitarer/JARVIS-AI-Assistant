"""Desktop shell. No network content is loaded into the conversation view."""

import html
from pathlib import Path

from PySide6.QtCore import QEvent, QProcess, Qt, Signal
from PySide6.QtGui import QCloseEvent, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QPushButton, QSizePolicy, QTextBrowser, QVBoxLayout, QWidget)

from jarvis import __version__
from jarvis.core.models import Message
from jarvis.ui.neural_runtime import create_visualizer


class SafeTranscript(QTextBrowser):
    def loadResource(self, resource_type, url):
        return None


class MainWindow(QMainWindow):
    submitted = Signal(str)
    stop_requested = Signal()
    settings_requested = Signal()
    activities_requested = Signal()
    clear_requested = Signal()
    close_requested = Signal()
    microphone_requested = Signal()
    listen_requested = Signal()
    overlay_requested = Signal()

    def __init__(self):
        super().__init__()
        self.allow_close = False
        self.close_to_tray = False
        self.busy = False
        self.assistant_name = "JARVIS · DEMO"
        self.ai_configured = False
        self.setWindowTitle("JARVIS · Qwen locale")
        self.resize(1280, 900)
        self.setMinimumSize(1040, 700)
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(34, 26, 34, 22)
        outer.setSpacing(20)

        header = QHBoxLayout()
        brand = QLabel("J A R V I S")
        brand.setObjectName("brand")
        header.addWidget(brand)
        subtitle = QLabel(f"PERSONAL DESKTOP ASSISTANT  /  LOCAL AI {__version__}")
        subtitle.setObjectName("eyebrow")
        header.addWidget(subtitle)
        header.addStretch()
        badge = self.provider_badge = QLabel("●  DEMO · AI NON COLLEGATA")
        badge.setObjectName("demoBadge")
        header.addWidget(badge)
        outer.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(32)
        stage = QVBoxLayout()
        stage.setSpacing(10)
        stage_header = QLabel("01  /  LOCAL CORE")
        stage_header.setObjectName("eyebrow")
        stage.addWidget(stage_header)
        self.visualizer = create_visualizer()
        self.visualizer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        stage.addWidget(self.visualizer, 5)
        self.state_label = QLabel("IN ATTESA")
        self.state_label.setObjectName("stateLabel")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stage.addWidget(self.state_label)
        local = self.provider_label = QLabel("ELABORAZIONE LOCALE  ·  NESSUNA CONNESSIONE AI")
        local.setObjectName("eyebrow")
        local.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stage.addWidget(local)
        self.action_label = QLabel("Pronto. Digita /aiuto oppure /apri blocco_note.")
        self.action_label.setWordWrap(True)
        self.action_label.setMinimumHeight(55)
        self.action_label.setObjectName("actionText")
        self.action_label.setTextFormat(Qt.TextFormat.PlainText)
        stage.addWidget(self.action_label)
        controls = QHBoxLayout()
        self.activities_button = QPushButton("Attività")
        self.activities_button.clicked.connect(self.activities_requested)
        self.settings_button = QPushButton("Impostazioni")
        self.settings_button.clicked.connect(self.settings_requested)
        controls.addWidget(self.activities_button)
        controls.addWidget(self.settings_button)
        self.agents_button = QPushButton("Agenti")
        self.agents_button.setToolTip("Stato reale degli agenti Codex + Ruflo e STOP sviluppo")
        self.agents_button.clicked.connect(self._show_agents)
        controls.addWidget(self.agents_button)
        stage.addLayout(controls)
        voice_controls = QHBoxLayout()
        self.microphone_button = QPushButton("Microfono OFF")
        self.microphone_button.clicked.connect(self.microphone_requested)
        self.listen_button = QPushButton("Ascolta")
        self.listen_button.clicked.connect(self.listen_requested)
        self.overlay_button = QPushButton("Overlay")
        self.overlay_button.clicked.connect(self.overlay_requested)
        for button in (self.microphone_button, self.listen_button, self.overlay_button):
            voice_controls.addWidget(button)
        stage.addLayout(voice_controls)
        unavailable = self.microphone_label = QLabel("MICROFONO OFF · openWakeWord locale")
        unavailable.setObjectName("muted")
        unavailable.setWordWrap(True)
        stage.addWidget(unavailable)
        body.addLayout(stage, 10)

        conversation = QVBoxLayout()
        conversation.setSpacing(14)
        chat_header = QHBoxLayout()
        title = QLabel("02  /  CONVERSAZIONE")
        title.setObjectName("eyebrow")
        chat_header.addWidget(title)
        chat_header.addStretch()
        self.clear_button = QPushButton("Cancella…")
        self.clear_button.setObjectName("quietButton")
        self.clear_button.clicked.connect(self.clear_requested)
        chat_header.addWidget(self.clear_button)
        conversation.addLayout(chat_header)
        self.transcript = SafeTranscript()
        self.transcript.setOpenExternalLinks(False)
        self.transcript.setOpenLinks(False)
        self.transcript.setAccessibleName("Conversazione locale")
        conversation.addWidget(self.transcript, 1)
        self.stream_preview = SafeTranscript()
        self.stream_preview.setMaximumHeight(120)
        self.stream_preview.setAccessibleName("Risposta finale in generazione")
        self.stream_preview.hide()
        conversation.addWidget(self.stream_preview)
        self.artifact_button = QPushButton("Apri PDF verificato")
        self.artifact_button.hide()
        conversation.addWidget(self.artifact_button)
        hint = QLabel("Comandi locali espliciti · /aiuto · /app · /apri blocco_note")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        conversation.addWidget(hint)
        compose = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setMaxLength(8000)
        self.input.setPlaceholderText("Scrivi un messaggio o un comando…")
        self.input.setAccessibleName("Messaggio o comando")
        self.input.returnPressed.connect(self._submit)
        self.send_button = QPushButton("Invia  ↗")
        self.send_button.setObjectName("primaryButton")
        self.send_button.clicked.connect(self._submit)
        compose.addWidget(self.input, 1)
        compose.addWidget(self.send_button)
        conversation.addLayout(compose)
        storage = QLabel("MEMORIA LOCALE · SQLite · ultimi 200 messaggi visibili")
        storage.setObjectName("muted")
        conversation.addWidget(storage)
        body.addLayout(conversation, 12)
        outer.addLayout(body, 1)

        footer = QHBoxLayout()
        self.footer_label = QLabel(f"●  SISTEMA PRONTO     |     WINDOWS DESKTOP     |     V {__version__}")
        self.footer_label.setObjectName("eyebrow")
        footer.addWidget(self.footer_label)
        footer.addStretch()
        self.stop_button = QPushButton("■  STOP")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.setEnabled(False)
        self.stop_button.setToolTip("Interrompe l'attività. Gli effetti già completati restano. (Esc)")
        self.stop_button.clicked.connect(self.stop_requested)
        footer.addWidget(self.stop_button)
        outer.addLayout(footer)
        self.stop_shortcut = QShortcut(QKeySequence("Escape"), self)
        self.stop_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.stop_shortcut.activated.connect(self.stop_requested)
        self.set_messages([])

    def _submit(self) -> None:
        text = self.input.text().strip()
        if text and (not self.busy or getattr(self, "allow_busy_input", False)):
            self.input.clear()
            self.submitted.emit(text)

    def _show_agents(self):
        root = Path(__file__).resolve().parents[2]
        success, _ = QProcess.startDetached(str(root / ".venv/Scripts/pythonw.exe"),
                                          ["-B", str(root / "development/monitor.py")], str(root))
        if not success:
            self.action_label.setText("Impossibile aprire il pannello agenti. Usa Sviluppo_JARVIS.bat.")

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        if not busy:
            self.allow_busy_input = False
        for widget in (self.input, self.send_button, self.clear_button, self.settings_button):
            widget.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
        self.footer_label.setText("●  ATTIVITÀ IN CORSO     |     ESC PER INTERROMPERE" if busy
                                  else f"●  SISTEMA PRONTO     |     WINDOWS DESKTOP     |     V {__version__}")
        if not busy:
            self.input.setFocus()

    def set_state(self, state: str) -> None:
        self.visualizer.set_state(state)
        labels = {"thinking": "QWEN · GENERAZIONE", "listening": "TI ASCOLTO", "speaking": "RISPOSTA VOCALE",
                  "confirmation": "CONFERMA RICHIESTA"}
        self.state_label.setText(labels.get(state, self.visualizer.LABELS[self.visualizer.state]))

    def set_provider(self, model: str | None, available: bool | None = None):
        self.ai_configured = bool(model)
        self.assistant_name = "JARVIS · QWEN" if model else "JARVIS · DEMO"
        if model:
            status = "COLLEGATO" if available is True else "NON DISPONIBILE" if available is False else "DA VERIFICARE"
            self.provider_badge.setText("●  OLLAMA · " + status)
            self.provider_label.setText("LOCALE  /  " + model)
        else:
            self.provider_badge.setText("●  DEMO · AI NON COLLEGATA")

    def set_stream(self, text: str):
        self.stream_preview.setVisible(bool(text))
        self.stream_preview.setPlainText(text)
        self.stream_preview.verticalScrollBar().setValue(self.stream_preview.verticalScrollBar().maximum())

    def set_messages(self, messages: list[Message]) -> None:
        parts = []
        names = {"user": "TU", "assistant": self.assistant_name, "system": "SISTEMA"}
        for message in messages:
            color = "#bdd2dd" if message.role == "user" else "#55d7eb" if message.role == "assistant" else "#ffb69e"
            content = html.escape(message.content).replace("\n", "<br>")
            parts.append(f'<p style="margin-top:20px;color:{color};font-size:10px;">'
                         f'{names[message.role]} · {html.escape(message.created_at[:16].replace("T", " "))} UTC</p>'
                         f'<p style="color:#dce8ef;margin-bottom:22px;line-height:145%;">{content}</p>')
        if not parts:
            parts = ['<p style="color:#55d7eb;margin-top:24px;">BENVENUTO IN JARVIS</p>'
                     '<p style="color:#bdd2dd;line-height:150%;">La base del tuo assistente desktop.<br><br>'
                     'Questa versione esegue comandi locali autorizzati e conserva la conversazione sul PC.<br><br>'
                     'Digita <b>/aiuto</b> per iniziare.<br>' +
                     ('Provider: Qwen 3.5 9B tramite Ollama locale.</p>' if self.ai_configured else 'Il provider AI non è ancora collegato.</p>')]
        self.transcript.setHtml("".join(parts))
        self.transcript.verticalScrollBar().setValue(self.transcript.verticalScrollBar().maximum())

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.visualizer.set_suspended(self.isMinimized())

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.allow_close:
            if hasattr(self.visualizer, "dispose"):
                self.visualizer.dispose()
            event.accept()
        elif self.close_to_tray:
            event.ignore()
            self.hide()
        else:
            event.ignore()
            self.close_requested.emit()
            # Qt suppresses recursive close() calls inside this closeEvent.
            # The presenter may have completed shutdown synchronously.
            if self.allow_close:
                event.accept()
