"""Project-local activation channel and responsive local-service startup."""

import hashlib
import json
from pathlib import Path
import queue
import threading

from PySide6.QtCore import QObject, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def instance_name(root):
    return "jarvis-desktop-" + hashlib.sha256(str(Path(root).resolve()).casefold().encode()).hexdigest()[:24]


def request_existing(root, action="show", *, timeout=400):
    if action not in {"show", "quit"}:
        raise ValueError("Unknown desktop activation action")
    socket = QLocalSocket()
    socket.connectToServer(instance_name(root))
    if not socket.waitForConnected(timeout):
        return False
    socket.write((action + "\n").encode("ascii"))
    socket.flush()
    socket.waitForBytesWritten(timeout)
    accepted = socket.waitForReadyRead(timeout) and bytes(socket.readAll()).strip() == b"ok"
    socket.abort()
    return bool(accepted)


class InstanceChannel(QObject):
    """Only activate/close this app; never expose tools, files or shell commands."""

    def __init__(self, root, desktop):
        super().__init__(desktop)
        self.desktop = desktop
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        name = instance_name(root)
        # Caller already holds the project QLockFile; no live peer can own it.
        QLocalServer.removeServer(name)
        if not self.server.listen(name):
            raise RuntimeError("Unable to open the project activation channel")
        self.server.newConnection.connect(self._connected)

    def _connected(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.readyRead.connect(lambda peer=socket: self._message(peer))
            socket.disconnected.connect(socket.deleteLater)
            QTimer.singleShot(1500, socket.disconnectFromServer)
            self._message(socket)

    def _message(self, socket):
        if socket.bytesAvailable() > 128:
            socket.abort()
            return
        if not socket.canReadLine():
            return
        action = bytes(socket.readLine()).strip()
        if action not in {b"show", b"quit"}:
            socket.abort()
            return
        socket.write(b"ok\n")
        socket.flush()
        socket.disconnectFromServer()
        QTimer.singleShot(0, self.desktop.show_dashboard if action == b"show" else self.desktop.quit)


class LocalServiceStartup(QObject):
    """Ollama boot may take 30 s; do it off the GUI thread with a bounded poll."""

    def __init__(self, presenter):
        super().__init__(presenter)
        self.presenter = presenter
        self.results = queue.Queue(maxsize=1)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._poll)
        self.status = "starting"

    def start(self):
        settings = self.presenter.controller.settings
        self.presenter.probe_needed = False

        def worker():
            try:
                from scripts.start_background import ensure_ollama
                path = settings.root / "data/logs/startup.log"
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as output:
                    ensure_ollama(settings.ollama, output)
                self.results.put((True, ""))
            except Exception as exc:
                self.results.put((False, str(exc)[:500]))
        self.presenter.window.action_label.setText("Avvio servizi locali… La finestra è già utilizzabile.")
        threading.Thread(target=worker, name="jarvis-local-startup", daemon=True).start()
        self.timer.start()

    def _poll(self):
        if self.presenter.closing:
            self.timer.stop()
            return
        try:
            success, message = self.results.get_nowait()
        except queue.Empty:
            return
        self.timer.stop()
        self.status = "ready" if success else "failed"
        if success:
            if self.presenter.worker is None:
                self.presenter.start({"kind": "provider_check"})
            else:
                self.presenter.probe_needed = True
        else:
            self.presenter.window.action_label.setText("Avvio Ollama non riuscito: " + message)
            self.presenter.window.set_provider(self.presenter.controller.settings.ollama.model, False)
