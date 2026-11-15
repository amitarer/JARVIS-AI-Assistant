"""Small read-only inspector inside the existing JARVIS desktop application."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QTextBrowser, QVBoxLayout
from jarvis.brain.ollama_inventory import describe_inventory


class ModelStatusDialog(QDialog):
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JARVIS · Modello locale")
        self.resize(600, 460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("MODELLO LOCALE / STATO VERIFICATO"))
        self.details = QTextBrowser()
        self.details.setOpenLinks(False)
        self.details.setOpenExternalLinks(False)
        self.details.setPlainText("Verifica dello stato Ollama in corso…")
        layout.addWidget(self.details, 1)
        self.refresh_button = QPushButton("Aggiorna stato")
        self.refresh_button.clicked.connect(self.refresh_requested)
        layout.addWidget(self.refresh_button)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.button(QDialogButtonBox.StandardButton.Close).setText("Chiudi")
        close.rejected.connect(self.close)
        layout.addWidget(close)

    def set_status(self, event):
        if event.get("local_inventory"):
            self.details.setPlainText(describe_inventory(event["local_inventory"]))
        elif event.get("available") is False:
            self.details.setPlainText(event.get("message", "Ollama locale non disponibile."))
        else:
            self.details.setPlainText("Modello disponibile. Aggiorna per verificare caricamento e memoria.")
