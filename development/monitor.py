"""Local supervision window; starts only the approved one-shot task on click."""

import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from development.orchestrator.permissions import STATE

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMainWindow, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget


def process_alive(pid):
    if type(pid) is not int or pid <= 0:
        return False
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259)
    finally:
        kernel.CloseHandle(handle)


class DevelopmentMonitor(QMainWindow):
    def __init__(self, *, state_directory=STATE):
        super().__init__()
        self.state_directory = Path(state_directory).resolve()
        if not self.state_directory.is_relative_to(STATE.resolve()):
            raise ValueError("Monitor state must remain inside the project development directory")
        self.setWindowTitle("JARVIS · Supervisione sviluppo · Ruflo + Codex")
        self.resize(1060, 720)
        self.setStyleSheet("QWidget {background:#080e16;color:#dce7ef;font:13px 'Segoe UI';} "
                          "QPushButton {padding:9px;background:#152333;border:1px solid #34475b;} "
                          "QPushButton:disabled {color:#657382;} QTableWidget {gridline-color:#263442;} "
                          "QHeaderView::section {background:#14202e;padding:6px;}")
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 24, 24, 24)
        title = QLabel("JARVIS / SVILUPPO SUPERVISIONATO")
        title.setStyleSheet("font-size:22px;")
        layout.addWidget(title)
        self.status_label = QLabel("Lettura dello stato locale…")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.task = QLabel()
        self.task.setWordWrap(True)
        layout.addWidget(self.task)
        self.agents = QTableWidget(0, 5)
        self.agents.setHorizontalHeaderLabels(["Ruolo", "Stato reale", "PID Codex", "Durata", "Token nuovi / cache"])
        self.agents.horizontalHeader().setStretchLastSection(True)
        self.agents.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.agents, 1)
        self.tests = QLabel()
        self.tests.setWordWrap(True)
        layout.addWidget(self.tests)
        self.resources = QLabel()
        self.resources.setWordWrap(True)
        layout.addWidget(self.resources)
        self.review = QLabel()
        self.review.setWordWrap(True)
        layout.addWidget(self.review)
        self.error = QLabel()
        self.error.setStyleSheet("color:#f1b192;")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QHBoxLayout()
        self.start = QPushButton("Avvia prova autorizzata · un ciclo")
        self.start.clicked.connect(self.start_once)
        buttons.addWidget(self.start)
        self.stop = QPushButton("STOP sviluppo")
        self.stop.setStyleSheet("QPushButton {background:#582821;color:#fff0eb;padding:12px;}")
        self.stop.clicked.connect(self.request_stop)
        buttons.addWidget(self.stop)
        self.report_button = QPushButton("Apri riepilogo")
        self.report_button.clicked.connect(lambda: self.open_local("report"))
        buttons.addWidget(self.report_button)
        self.worktree_button = QPushButton("Apri worktree")
        self.worktree_button.clicked.connect(lambda: self.open_local("worktree"))
        buttons.addWidget(self.worktree_button)
        layout.addLayout(buttons)
        note = QLabel("Massimo 4 ruoli · Un autore del codice alla volta · Nessun merge automatico · Avvio con Windows disattivato")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.state = {}
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self):
        path = self.state_directory / "status.json"
        try:
            if path.is_file() and path.stat().st_size <= 2_000_000:
                self.state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        state = self.state
        status = state.get("status", "not_started")
        live = status in {"starting", "running", "recovering"} and process_alive(state.get("runner_pid"))
        labels = {"ready_for_review": "Prova completata · integrazione da valutare", "running": "In esecuzione",
                  "recovering": "Ripresa esplicita della prova", "cancelled": "Interrotto con STOP",
                  "failed": "Arrestato per un errore", "idle": "Nessuna attività autorizzata in attesa",
                  "not_started": "Pronto per il primo collaudo", "starting": "Avvio"}
        summary = labels.get(status, status)
        if status in {"starting", "running", "recovering"} and not live:
            summary = "Processo non attivo · stato precedente conservato, nessuna ripresa automatica"
        self.status_label.setText(f"{summary}  /  Fase: {state.get('stage', '—')}  /  {state.get('elapsed_seconds', 0):.1f} s")
        worktree = state.get("worktree", {})
        self.task.setText(f"Attività: {state.get('task_id', '—')} · {state.get('task_title', '')}\n"
                          f"Branch: {worktree.get('branch', '—')} · Fixture sintetica separata dal codice operativo")
        rows = state.get("agents", [])
        self.agents.setRowCount(len(rows))
        for index, row in enumerate(rows):
            usage = row.get("usage", {})
            cached = usage.get("cached_input_tokens", 0)
            fresh = max(0, usage.get("input_tokens", 0) - cached) + usage.get("output_tokens", 0)
            status_text = row.get("status", "assegnato")
            if row.get("result_note"):
                status_text += " / test bloccati"
            if status_text == "running" and not process_alive(row.get("target_pid")):
                status_text = "processo terminato"
            values = [row["role"], status_text, str(row.get("target_pid", "non avviato")),
                      str(row.get("seconds", "—")), f"{fresh} / {cached}"]
            for column, value in enumerate(values):
                self.agents.setItem(index, column, QTableWidgetItem(value))
        self.agents.resizeColumnsToContents()
        tests = state.get("tests", [])
        self.tests.setText("Test misurati: " + (" · ".join(f"{item['label']}: exit {item['exit_code']}" for item in tests) or "non eseguiti"))
        resource = state.get("resources", {})
        self.resources.setText(f"Processi del ciclo: {resource.get('active_processes', 0)} · Picco memoria: "
                               f"{resource.get('peak_job_memory_mib', 0)} MiB · Limiti: CPU 25%, RAM 8192 MiB\n"
                               "La VRAM non ha un limite rigido; nessuna inferenza Ollama viene avviata da questa prova.")
        review = state.get("review", {})
        self.review.setText("Revisione: " + review.get("summary", "non ancora eseguita"))
        self.error.setText("\n".join(state.get("errors", [])))
        self.stop.setEnabled(live)
        self.start.setEnabled(not state and not live)
        self.report_button.setEnabled(bool(state.get("run_directory")))
        self.worktree_button.setEnabled(bool(worktree.get("workspace")))

    def request_stop(self):
        self.state_directory.mkdir(exist_ok=True)
        (self.state_directory / "STOP").write_text("User pressed the dedicated development STOP button\n", encoding="utf-8")
        self.stop.setEnabled(False)
        self.status_label.setText("STOP richiesto · arresto del solo albero processi del ciclo")

    def start_once(self):
        STATE.mkdir(exist_ok=True)
        with (STATE / "launcher.log").open("ab") as output:
            subprocess.Popen([str(ROOT / ".venv/Scripts/pythonw.exe"), "-B", "-m", "development.orchestrator", "run", "--once"],
                             cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        self.start.setEnabled(False)

    def open_local(self, kind):
        if kind == "report":
            path = Path(self.state.get("run_directory", "")) / "report.md"
            allowed = STATE / "runs"
        else:
            path = Path(self.state.get("worktree", {}).get("workspace", ""))
            allowed = STATE / "worktrees"
        if path.exists() and path.resolve().is_relative_to(allowed.resolve()):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))


def main():
    app = QApplication.instance() or QApplication([])
    window = DevelopmentMonitor()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
