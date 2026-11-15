"""Offscreen Qt checks exercise event delivery and real worker lifecycles."""

import os
from dataclasses import replace
import json
import threading
import time
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from jarvis.core.models import ToolResult
from jarvis.core.models import Event
from jarvis.ui.main_window import MainWindow
from jarvis.ui.presenter import Presenter
from jarvis.ui.background import BackgroundDesktop
from tests.support import PROJECT, make_controller, temporary_project


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # Qt's offscreen Windows plugin does not enumerate system fonts.
        for font in ("segoeui.ttf", "segoeuil.ttf", "consola.ttf"):
            QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts") / font))
        cls.app.setQuitOnLastWindowClosed(False)
        cls.app.setStyleSheet((PROJECT / "jarvis/ui/theme.qss").read_text(encoding="utf-8"))

    def setUp(self):
        self.temp = temporary_project()
        self.controller = make_controller(Path(self.temp.name))
        self.window = MainWindow()
        self.presenter = Presenter(self.window, self.controller)
        self.window.show()
        self.presenter.start({"kind": "refresh"})
        self.wait_until(lambda: self.presenter.worker is None)

    def tearDown(self):
        self.presenter.close()
        self.wait_until(lambda: self.presenter.worker is None)
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def wait_until(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertTrue(predicate(), "Qt operation exceeded deadline")

    def test_chat_is_delivered_by_worker_and_markup_is_plain_text(self):
        text = '<img src="https://example.invalid/secret"> <b>message</b>'
        self.window.input.setText(text)
        self.window.send_button.click()
        self.wait_until(lambda: self.presenter.worker is None)
        self.assertIn(text, self.window.transcript.toPlainText())
        self.assertIn("Nessun modello AI", self.window.transcript.toPlainText())
        self.assertFalse(self.window.busy)

    def test_gui_remains_responsive_and_stop_cancels_a_running_tool(self):
        ticks = []
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(1))
        started = threading.Event()
        def slow_tool(arguments, context):
            started.set()
            while True:
                context.checkpoint()
                time.sleep(0.01)
        with patch.object(self.controller.tools._tools["open_application"], "execute", side_effect=slow_tool):
            timer.start()
            self.presenter.start({"kind": "chat", "text": "/apri blocco_note"})
            self.wait_until(lambda: started.is_set() and len(ticks) >= 8)
            self.window.stop_button.click()
            self.wait_until(lambda: self.presenter.worker is None)
            timer.stop()
        self.assertGreaterEqual(len(ticks), 8)
        self.assertEqual(self.controller.repository.tasks()[0]["status"], "cancelled")

    def test_stop_while_waiting_for_approval_preserves_history(self):
        self.controller.repository.add_message("user", "keep me")
        self.presenter.start({"kind": "clear_history"})
        self.wait_until(lambda: self.presenter.approval is not None)
        self.assertTrue(self.window.stop_button.isEnabled())
        self.window.stop_button.click()
        self.wait_until(lambda: self.presenter.worker is None)
        self.assertIsNone(self.presenter.approval)
        self.assertIn("keep me", [m.content for m in self.controller.repository.messages()])
        self.assertEqual(self.controller.repository.tasks()[0]["status"], "cancelled")

    def test_activity_inspection_does_not_block_stop(self):
        self.presenter.start({"kind": "clear_history"})
        self.wait_until(lambda: self.presenter.approval is not None)
        self.presenter.activities()
        self.assertFalse(self.presenter.activity_dialog.isModal())
        self.assertFalse(self.presenter.approval.isModal())
        self.assertIn("waiting_approval", self.presenter.activity_dialog.text.toPlainText())
        self.window.stop_button.click()
        self.wait_until(lambda: self.presenter.worker is None)
        self.assertEqual(self.controller.repository.tasks()[0]["status"], "cancelled")

    def test_accepting_concrete_dialog_deletes_history(self):
        self.controller.repository.add_message("user", "remove me")
        self.presenter.start({"kind": "clear_history"})
        self.wait_until(lambda: self.presenter.approval is not None)
        self.presenter.approval.accept()
        self.wait_until(lambda: self.presenter.worker is None)
        messages = [m.content for m in self.controller.repository.messages()]
        self.assertNotIn("remove me", messages)
        self.assertTrue(any("Cronologia cancellata" in text for text in messages))

    def test_preferences_update_animation_and_survive_refresh(self):
        self.presenter.start({"kind": "preferences", "reduced_motion": True, "log_level": "WARNING"})
        self.wait_until(lambda: self.presenter.worker is None)
        self.assertTrue(self.window.visualizer.reduced_motion)
        self.assertFalse(self.window.visualizer.timer.isActive())
        self.presenter.start({"kind": "refresh"})
        self.wait_until(lambda: self.presenter.worker is None)
        self.assertEqual(self.presenter.log_level, "WARNING")

    def test_reduced_motion_minimization_and_snapshot(self):
        self.window.visualizer.set_suspended(True)
        self.assertFalse(self.window.visualizer.timer.isActive())
        self.window.visualizer.set_suspended(False)
        self.assertTrue(self.window.visualizer.timer.isActive())
        self.window.visualizer.set_reduced_motion(True)
        self.assertFalse(self.window.visualizer.timer.isActive())
        self.window.visualizer.set_reduced_motion(False)
        self.app.processEvents()
        destination = PROJECT / "data/verification/foundation-offscreen.png"
        destination.parent.mkdir(exist_ok=True)
        self.assertTrue(self.window.grab().save(str(destination)))

    def test_close_during_approval_cancels_worker_without_thread_destruction(self):
        self.presenter.start({"kind": "clear_history"})
        self.wait_until(lambda: self.presenter.approval is not None)
        self.window.close()
        self.wait_until(lambda: self.presenter.worker is None)
        self.assertFalse(self.window.isVisible())

    def test_idle_window_closes_synchronously(self):
        self.window.close()
        self.app.processEvents()
        self.assertFalse(self.window.isVisible())

    def test_streamed_text_never_goes_to_tts_and_final_answer_is_filtered(self):
        with patch.object(self.presenter.speech, "speak") as speak:
            self.presenter.on_event(Event("stream_start"))
            self.presenter.on_event(Event("stream", "Risposta parziale"))
            self.presenter._flush_stream()
            speak.assert_not_called()
            self.assertIn("Risposta parziale", self.window.stream_preview.toPlainText())
            self.presenter.on_event(Event("response", "<think>PRIVATE</think>Risposta finale."))
            self.assertEqual(self.presenter.last_response, "Risposta finale.")
            self.assertNotIn("PRIVATE", self.window.transcript.toPlainText())
            self.presenter.voice_turn = True
            self.presenter.worker = SimpleNamespace(cancellation=threading.Event())
            self.presenter.on_event(Event("response", "<think>PRIVATE</think>Risposta da leggere."))
            speak.assert_called_once_with("Risposta da leggere.")
            self.presenter.worker = None
            self.presenter.voice_turn = False

    def test_overlay_is_hidden_before_execution_barrier_is_released(self):
        self.presenter.overlay.present("thinking")
        ack = threading.Event()
        self.presenter.on_event(Event("execution_barrier", {"ack": ack, "tool": "open_application"}))
        self.assertTrue(ack.is_set())
        self.assertFalse(self.presenter.overlay.isVisible())

    def test_muting_response_audio_persists_and_never_disables_microphone(self):
        microphone_enabled = self.presenter.voice.enabled
        with patch.object(self.presenter.speech, "speak") as speak:
            self.window.response_audio_button.click()
            self.assertFalse(self.controller.repository.preferences()["response_audio"])
            self.presenter.voice_turn = True
            self.presenter.worker = SimpleNamespace(cancellation=threading.Event())
            self.presenter.on_event(Event("response", "Testo da mostrare senza pronunciarlo."))
            speak.assert_not_called()
            self.presenter.worker = None
            self.presenter.voice_turn = False
        self.assertEqual(self.presenter.voice.enabled, microphone_enabled)

    def test_reading_barrier_is_silent_and_released_immediately(self):
        self.presenter.voice_turn = True
        acknowledgement = threading.Event()
        with patch.object(self.presenter.speech, "speak") as speak:
            self.presenter.on_event(Event("execution_barrier", {"tool": "read_web_page", "ack": acknowledgement}))
        speak.assert_not_called()
        self.assertTrue(acknowledgement.is_set())
        self.presenter.voice_turn = False

    def test_explicit_silent_turn_does_not_speak_final_answer(self):
        self.presenter.voice_turn = True
        self.presenter.silent_turn = True
        self.presenter.worker = SimpleNamespace(cancellation=threading.Event())
        with patch.object(self.presenter.speech, "speak") as speak:
            self.presenter.on_event(Event("response", "Risultato letto dal sito."))
        speak.assert_not_called()
        self.presenter.worker = None
        self.presenter.voice_turn = False

    def test_website_content_is_silent_unless_reading_aloud_is_explicit(self):
        self.presenter.voice_turn = True
        self.presenter.worker = SimpleNamespace(cancellation=threading.Event())
        with patch.object(self.presenter.speech, "speak") as speak:
            self.presenter.on_event(Event("action", {"tool": "read_web_page"}))
            self.presenter.on_event(Event("response", "Contenuto del sito."))
            speak.assert_not_called()
            self.presenter.read_aloud = True
            self.presenter.on_event(Event("response", "Contenuto richiesto ad alta voce."))
            speak.assert_called_once_with("Contenuto richiesto ad alta voce.")
        self.presenter.worker = None
        self.presenter.voice_turn = False

    def test_no_overlay_appears_for_background_thinking_without_wake(self):
        self.presenter.voice_turn = True
        self.presenter.on_event(Event("state", "thinking"))
        self.assertFalse(self.presenter.overlay.isVisible())
        self.presenter.voice_turn = False

    def test_voice_intention_finishes_before_overlay_closes_and_action_is_released(self):
        self.presenter.voice_turn = True
        self.presenter._wake_activated()
        ack = threading.Event()
        with patch.object(self.presenter.speech, "speak", return_value=True):
            self.presenter.on_event(Event("execution_barrier", {"ack": ack, "tool": "open_application"}))
            self.presenter._speech_started()
            self.assertFalse(ack.is_set())
            self.assertTrue(self.presenter.overlay.isVisible())
            self.presenter._speech_finished()
        self.assertTrue(ack.is_set())
        self.assertFalse(self.presenter.overlay.isVisible())
        self.presenter.on_event(Event("state", "thinking"))
        self.presenter._speech_started()
        self.assertFalse(self.presenter.overlay.isVisible())
        self.presenter.voice.set_playback(False)
        self.presenter.voice_turn = False

    def test_after_voice_turn_returns_to_hidden_wake_word_mode(self):
        self.presenter.voice.settings = replace(self.presenter.voice.settings, continuous_conversation=False)
        self.presenter.voice.enabled = True
        self.presenter._wake_activated()
        self.presenter.voice.complete_turn()
        self.assertEqual(self.presenter.voice.phase, "wake")
        self.assertFalse(self.presenter.overlay.isVisible())
        self.presenter.voice.enabled = False

    def test_follow_up_keeps_listening_with_overlay_hidden(self):
        self.presenter.voice.enabled = True
        self.presenter.voice_turn = True
        self.presenter._wake_activated()
        self.presenter.voice.settings = replace(self.presenter.voice.settings, continuous_conversation=True)
        self.presenter._speech_finished()
        self.assertEqual(self.presenter.voice.phase, "listening")
        self.assertFalse(self.presenter.overlay.isVisible())
        self.assertFalse(self.presenter.overlay_cycle)
        self.presenter.voice.enabled = False

    def test_wake_preserves_command_audio_and_rearms_after_conversation(self):
        voice = self.presenter.voice
        detector = Mock()
        detector.suspended = threading.Event()
        detector.isRunning.return_value = False
        voice.wake = detector
        voice.enabled = True
        voice.phase = "wake"
        voice._frames(np.full(1600, 3000, dtype=np.int16))
        voice._wake()
        self.assertEqual(voice.phase, "listening")
        self.assertEqual(voice.total_samples, 1600)
        self.assertEqual(voice.parts[0][0], 3000)
        self.assertTrue(detector.suspended.is_set())
        voice.end_conversation()
        self.assertEqual(voice.phase, "wake")
        self.assertFalse(detector.suspended.is_set())
        voice.enabled = False
        voice.wake = None

    def test_saying_only_jarvis_during_follow_up_opens_listening_overlay(self):
        voice = self.presenter.voice
        voice.enabled = True
        voice.phase = "processing"
        self.presenter.overlay_cycle = False
        voice._text("Jarvis", voice.generation)
        self.assertEqual(voice.phase, "listening")
        self.assertTrue(self.presenter.overlay.isVisible())
        voice.enabled = False

    def test_autonomous_stop_monitor_ignores_other_speech_and_accepts_stop(self):
        voice = self.presenter.voice
        voice.enabled = True
        commands = []
        voice.command.connect(commands.append)
        voice.monitor_stop()
        voice._text("apri qualcosa", voice.generation)
        self.assertEqual(commands, [])
        self.assertEqual(voice.phase, "control")
        voice._text("stop", voice.generation)
        self.assertFalse(voice.control_only)
        self.assertEqual(voice.phase, "wake")
        voice.enabled = False

    def test_typed_stop_works_while_autonomous_worker_is_busy(self):
        worker = Mock()
        worker.cancellation = threading.Event()
        worker.cancel.side_effect = worker.cancellation.set
        self.presenter.worker = worker
        self.window.set_busy(True)
        self.presenter.on_event(Event("autonomy", {"active":True,"turns":0,"stage":"Test","objective":"Test"}))
        self.window.input.setText("STOP")
        self.window.send_button.click()
        self.assertTrue(worker.cancellation.is_set())
        self.assertFalse(self.presenter.autonomy_active)
        self.assertFalse(self.presenter.voice.control_only)
        self.presenter.worker = None

    def test_research_artifact_button_opens_only_delivered_local_pdf(self):
        folder = Path(self.temp.name)/"data/reports/test"
        folder.mkdir(parents=True)
        pdf = folder/"ricerca.pdf"
        pdf.write_bytes(b"%PDF-test")
        self.presenter.on_event(Event("artifact",{"path":str(pdf),"verified":False}))
        self.assertTrue(self.window.artifact_button.isHidden())
        self.presenter.on_event(Event("artifact",{"path":str(pdf),"verified":True}))
        self.assertFalse(self.window.artifact_button.isHidden())
        with patch("jarvis.ui.presenter.QDesktopServices.openUrl",return_value=True) as opener:
            self.window.artifact_button.click()
        self.assertEqual(Path(opener.call_args.args[0].toLocalFile()),pdf)

    def test_research_worker_exports_real_pdf_and_delivers_button(self):
        from jarvis.brain.ollama import OllamaProvider
        from jarvis.core.models import ToolCall
        from jarvis.research.report import export_pdf
        from jarvis.tools.research import RunResearchTool,ResearchOperationTool
        from tests.test_research import PLAN,SOURCES,REPORT
        self.controller.settings = replace(self.controller.settings,ollama=replace(self.controller.settings.ollama,enabled=True))
        self.presenter.probe_needed = False
        services = Mock(root=Path(self.temp.name))
        services.search.return_value = {"results":[{"url":s["url"]} for s in SOURCES],"engine":"fixture"}
        services.fetch.side_effect = lambda url,ctx:dict(next(s for s in SOURCES if s["url"]==url))
        services.pdf.side_effect = export_pdf
        self.controller.tools.register(RunResearchTool())
        for operation in ("search","fetch","pdf","chatgpt","google_docs"):
            self.controller.tools.register(ResearchOperationTool(services,operation))
        with patch.object(OllamaProvider,"check",return_value={"model":"test"}), \
                patch.object(OllamaProvider,"chat",return_value=("",[ToolCall("run_research",json.dumps(PLAN))],{})), \
                patch.object(OllamaProvider,"relevant_sources",side_effect=lambda topic,sources,ctx:sources), \
                patch.object(OllamaProvider,"assess_research",return_value={"sufficient":True,"gaps":[],"queries":[]}), \
                patch.object(OllamaProvider,"review_report",return_value={"approved":True,"issues":[],"notes":[]}), \
                patch.object(OllamaProvider,"research_report",side_effect=lambda *a,**kw:json.loads(json.dumps(REPORT))):
            self.presenter.start({"kind":"chat","text":"Prepara un rapporto scientifico in PDF"})
            self.wait_until(lambda:self.presenter.approval is not None)
            self.presenter.approval.accept()
            self.wait_until(lambda:self.presenter.worker is None,timeout=10)
        self.assertFalse(self.window.artifact_button.isHidden())
        self.assertTrue(self.presenter.artifact_path.is_file())
        self.assertEqual(self.controller.repository.tasks()[0]["status"],"succeeded")

    def test_research_progress_uses_sources_and_stop_remains_available(self):
        worker = Mock()
        worker.cancellation = threading.Event()
        worker.cancel.side_effect = worker.cancellation.set
        self.presenter.worker = worker
        self.window.set_busy(True)
        self.presenter.on_event(Event("autonomy",{"active":True,"mode":"research","turns":3,"stage":"Redigo il rapporto"}))
        self.assertIn("3 fonti lette",self.window.action_label.text())
        self.assertTrue(self.window.input.isEnabled())
        self.window.input.setText("STOP")
        self.window.send_button.click()
        self.assertTrue(worker.cancellation.is_set())
        self.presenter.worker = None

    def test_progress_updates_preserve_incoming_stop_audio(self):
        worker=Mock()
        worker.cancellation=threading.Event()
        self.presenter.worker=worker
        self.presenter.voice.enabled=True
        event=Event("autonomy",{"active":True,"mode":"task","turns":1,"stage":"Lettura"})
        self.presenter.on_event(event)
        samples=np.ones(3200,dtype=np.int16)
        self.presenter.voice.parts=[samples]
        self.presenter.voice.total_samples=3200
        self.presenter.on_event(event)
        self.assertEqual(self.presenter.voice.total_samples,3200)
        self.assertIs(self.presenter.voice.parts[0],samples)
        self.presenter.voice.enabled=False
        self.presenter.worker=None

    def test_dashboard_close_to_tray_does_not_shutdown_assistant(self):
        self.window.close_to_tray = True
        self.presenter.voice.enabled = True
        self.window.close()
        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.presenter.closing)
        self.assertTrue(self.presenter.voice.enabled)
        self.presenter.voice.enabled = False
        self.window.close_to_tray = False

    def test_no_system_tray_falls_back_to_a_visible_dashboard(self):
        with patch("jarvis.ui.background.QSystemTrayIcon.isSystemTrayAvailable", return_value=False):
            desktop = BackgroundDesktop(self.presenter)
            with patch.object(self.presenter.voice, "enable") as enable:
                desktop.start(dashboard=False, auto_listen=True)
                self.assertTrue(self.window.isVisible())
                self.wait_until(lambda: self.presenter.worker is None)
                self.wait_until(lambda: enable.called)

    def test_runtime_status_reports_real_capture_counters_without_audio(self):
        with patch("jarvis.ui.background.QSystemTrayIcon.isSystemTrayAvailable", return_value=False):
            desktop = BackgroundDesktop(self.presenter)
            self.presenter.voice.audio.captured_samples = 16000
            self.presenter.voice.audio.peak_rms = 0.0
            desktop.write_status()
            payload = json.loads((Path(self.temp.name) / "data/runtime.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["microphone"]["samples"], 16000)
        self.assertEqual(payload["microphone"]["peak_rms"], 0.0)
        self.assertFalse(payload["wake"]["ready"])
        self.assertNotIn("audio", payload)
        self.assertNotIn("transcript", payload)
