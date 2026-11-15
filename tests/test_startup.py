"""Startup must leave Qt responsive and report local service failure truthfully."""

import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from jarvis.ui.startup import LocalServiceStartup


class StartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for(self, predicate):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(0.005)
        self.fail("Startup callback timed out")

    def presenter(self, root):
        presenter = QObject()
        presenter.controller = SimpleNamespace(settings=SimpleNamespace(root=root, ollama=SimpleNamespace(model="test", enabled=False)))
        presenter.window = SimpleNamespace(action_label=QLabel(), set_provider=lambda *args: presenter.providers.append(args))
        presenter.worker = None
        presenter.closing = False
        presenter.probe_needed = True
        presenter.calls, presenter.providers = [], []
        presenter.start = presenter.calls.append
        return presenter

    def test_waiting_for_local_server_does_not_block_ui_or_check_provider_early(self):
        release = threading.Event()
        entered = threading.Event()
        with tempfile.TemporaryDirectory() as temporary:
            presenter = self.presenter(Path(temporary))
            service = LocalServiceStartup(presenter)

            def slow_service(*args):
                entered.set()
                release.wait(3)

            with patch("scripts.start_background.ensure_ollama", side_effect=slow_service):
                try:
                    service.start()
                    self.wait_for(entered.is_set)
                    clicks = []
                    button = QPushButton()
                    button.clicked.connect(lambda: clicks.append(True))
                    button.click()
                    self.assertEqual(clicks, [True])
                    self.assertEqual(presenter.calls, [])
                    release.set()
                    self.wait_for(lambda: service.status == "ready")
                    self.assertEqual(presenter.calls, [{"kind": "provider_check"}])
                finally:
                    release.set()
                    self.wait_for(lambda: not service.timer.isActive())

    def test_local_server_failure_is_reported_without_claiming_ai_available(self):
        with tempfile.TemporaryDirectory() as temporary:
            presenter = self.presenter(Path(temporary))
            service = LocalServiceStartup(presenter)
            with patch("scripts.start_background.ensure_ollama", side_effect=RuntimeError("fixture unavailable")):
                service.start()
                self.wait_for(lambda: service.status == "failed")
            self.assertEqual(presenter.providers, [("test", False)])
            self.assertEqual(presenter.calls, [])
            self.assertIn("fixture unavailable", presenter.window.action_label.text())
