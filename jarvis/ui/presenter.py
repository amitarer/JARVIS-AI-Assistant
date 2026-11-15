"""UI lifecycle and main-thread-only widget updates."""

import logging
from pathlib import Path
from dataclasses import asdict

from PySide6.QtCore import QObject, Slot, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog

from jarvis.core.controller import Controller
from jarvis.core.models import Event
from jarvis.ui.dialogs import ActivityDialog, ApprovalDialog, SettingsDialog
from jarvis.ui.main_window import MainWindow
from jarvis.ui.workers import TaskWorker
from jarvis.ui.neural_runtime import create_overlay
from jarvis.voice.session import VoiceSession, spoken_control
from jarvis.voice.speech import SpeechOutput
from jarvis.voice.replies import spoken_reply
from jarvis.infrastructure.settings import validate_voice
from jarvis.brain.response_text import final_text
from jarvis.core.verified_reply import has_completion_claim


class Presenter(QObject):
    def __init__(self, window: MainWindow, controller: Controller):
        super().__init__(window)
        self.window = window
        self.controller = controller
        self.worker: TaskWorker | None = None
        self.approval: ApprovalDialog | None = None
        self.activity_dialog: ActivityDialog | None = None
        self.snapshot: dict = {"messages": [], "tasks": [], "preferences": {}}
        self.closing = False
        self.had_error = False
        self.reduced_motion = controller.settings.reduced_motion
        self.log_level = controller.settings.log_level
        self.overlay = create_overlay()
        self.model_status_dialog = None
        self.voice = VoiceSession(controller.settings.root, controller.settings.voice, self)
        self.speech = SpeechOutput(self)
        self.speech.voice_name = controller.settings.voice.voice_name
        self.voice_turn = False
        self.overlay_cycle = False
        self.actions_started = False
        self.autonomy_active = False
        self.artifact_path = None
        self.last_response = self.last_notice = ""
        self.response_received = False
        self.stream_buffer = ""
        self.execution_ack = None
        self.provider_info = {"available": None, "model": controller.settings.ollama.model}
        self.probe_needed = controller.settings.ollama.enabled
        self.stream_timer = QTimer(self)
        self.stream_timer.setInterval(60)
        self.stream_timer.timeout.connect(self._flush_stream)
        self.shutdown_timer = QTimer(self)
        self.shutdown_timer.setInterval(50)
        self.shutdown_timer.timeout.connect(self._finish_close)
        window.visualizer.set_reduced_motion(self.reduced_motion)
        self.overlay.set_reduced_motion(self.reduced_motion)
        window.set_provider(controller.settings.ollama.model if controller.settings.ollama.enabled else None)
        window.submitted.connect(self._submitted)
        window.stop_requested.connect(self.stop)
        window.artifact_button.clicked.connect(self.open_artifact)
        window.clear_requested.connect(lambda: self.start({"kind": "clear_history"}))
        window.settings_requested.connect(self.settings)
        window.activities_requested.connect(self.activities)
        window.close_requested.connect(self.close)
        window.microphone_requested.connect(self.toggle_microphone)
        window.listen_requested.connect(self.listen)
        window.overlay_requested.connect(lambda: self.overlay.present("listening", "Anteprima del cervello digitale", preview=True, timeout_ms=5000))
        window.model_status_requested.connect(self.show_model_status)
        self.voice.command.connect(self._voice_command)
        self.voice.state.connect(self._voice_state)
        self.voice.level.connect(self._input_level)
        self.voice.status.connect(window.microphone_label.setText)
        self.voice.enabled_changed.connect(lambda enabled: window.microphone_button.setText("Microfono ON" if enabled else "Microfono OFF"))
        self.voice.error.connect(self._voice_error)
        self.voice.stopped.connect(self.stop)
        self.voice.repeat.connect(self.repeat)
        self.voice.activated.connect(self._wake_activated)
        self.speech.started.connect(self._speech_started)
        self.speech.finished.connect(self._speech_finished)
        self.speech.level.connect(self.overlay.set_level)
        if hasattr(window.visualizer, "set_level"):
            self.speech.level.connect(window.visualizer.set_level)
        self.speech.error.connect(self._voice_error)

    def _submitted(self, text):
        if self.autonomy_active and self.worker:
            if spoken_control(text) in {"stop", "fermati", "annulla", "chiudi"}:
                self.stop()
            else:
                self.window.action_label.setText("Sessione autonoma in corso. Scrivi STOP o usa il pulsante STOP per interrompere.")
            return
        self.start({"kind": "chat", "text": text})

    def start(self, payload: dict) -> None:
        if self.worker is not None or self.closing:
            return
        self.voice_turn = payload.get("kind") == "voice"
        self.actions_started = False
        if not self.voice_turn:
            self.overlay_cycle = False
            self.overlay.dismiss()
        self.speech.stop()
        if payload.get("kind") not in {"refresh", "provider_check"}:
            self.voice.pause_for_task()
        self.stream_buffer = ""
        self.window.set_stream("")
        self.had_error = False
        self.response_received = False
        self.last_notice = ""
        self.window.set_busy(True)
        if self.model_status_dialog:
            self.model_status_dialog.refresh_button.setEnabled(False)
        self.window.set_state("executing")
        self.worker = TaskWorker(self.controller, payload, self)
        self.worker.event.connect(self.on_event)
        self.worker.finished.connect(self.finished)
        self.worker.start()

    @Slot(object)
    def on_event(self, event: Event) -> None:
        if event.kind == "snapshot":
            self.snapshot = event.data
            self.window.set_messages(event.data["messages"])
            if self.activity_dialog is not None:
                self.activity_dialog.set_tasks(event.data["tasks"])
            preferences = event.data["preferences"]
            self.reduced_motion = preferences.get("reduced_motion", self.controller.settings.reduced_motion)
            self.log_level = preferences.get("log_level", self.controller.settings.log_level)
            self.window.visualizer.set_reduced_motion(self.reduced_motion)
            self.overlay.set_reduced_motion(self.reduced_motion)
            try:
                values = {**asdict(self.controller.settings.voice), **preferences.get("voice", {})}
                self.voice.settings = validate_voice(values)
                self.speech.voice_name = self.voice.settings.voice_name
            except ValueError:
                self.window.action_label.setText("Preferenze vocali non valide: uso i valori iniziali.")
            logging.getLogger("jarvis").setLevel(self.log_level)
        elif event.kind == "notice":
            self.last_notice = event.data
            self.window.action_label.setText(event.data)
        elif event.kind == "state":
            self.had_error = event.data == "error"
            self.window.set_state(event.data)
            if event.data == "executing":
                self.overlay.dismiss()
            elif self.voice_turn and self.overlay_cycle and not self.actions_started and event.data in {"thinking", "error"}:
                self.overlay.present(event.data, self.last_notice if event.data == "error" else "")
        elif event.kind == "provider":
            self.provider_info = event.data
            self.window.set_provider(self.controller.settings.ollama.model, event.data["available"])
            if self.model_status_dialog:
                self.model_status_dialog.set_status(event.data)
        elif event.kind == "stream_start":
            self.stream_buffer = ""
            self.window.set_stream("")
        elif event.kind == "stream":
            self.stream_buffer += event.data
            if not self.stream_timer.isActive():
                self.stream_timer.start()
        elif event.kind == "response":
            self.response_received = True
            self.stream_timer.stop()
            self.window.set_stream("")
            self.last_response = final_text(event.data)
            if self.voice_turn and not self.closing and self.worker and not self.worker.cancellation.is_set():
                self.speech.speak(spoken_reply(self.last_response))
        elif event.kind == "action":
            self.window.action_label.setText("Strumento: " + event.data["tool"])
        elif event.kind == "artifact":
            path = Path(event.data.get("path", "")).resolve()
            if (event.data.get("verified") and path.suffix.casefold() == ".pdf" and path.is_file()
                    and path.is_relative_to(self.controller.settings.root.resolve()/"data/reports")):
                self.artifact_path = path
                self.window.artifact_button.setToolTip(str(path))
                self.window.artifact_button.show()
        elif event.kind == "autonomy":
            self.autonomy_active = bool(event.data["active"] and self.worker and not self.worker.cancellation.is_set())
            self.overlay_cycle = False
            self.overlay.dismiss()
            self.window.allow_busy_input = self.autonomy_active
            self.window.input.setEnabled(self.autonomy_active or self.worker is None)
            self.window.send_button.setEnabled(self.autonomy_active or self.worker is None)
            if self.autonomy_active:
                if not self.voice.control_only:
                    self.voice.monitor_stop()
                mode=event.data.get("mode")
                label = (f"Ricerca · {event.data['turns']} fonti lette" if mode=="research" else
                         f"Attivita' · {event.data['turns']} passaggi" if mode=="task" else f"Autonomia · {event.data['turns']} invii verificati")
                self.window.action_label.setText(label + " · " + event.data["stage"])
                if event.data.get("last_reply"):
                    self.window.set_stream("ChatGPT · risposta verificata:\n" + event.data["last_reply"][:5000])
            else:
                self.voice.stop_monitoring()
        elif event.kind == "execution_barrier":
            self.overlay.dismiss()
            self.execution_ack = event.data["ack"]
            intentions = {"open_application": "Avvio l'applicazione.", "read_operations": "Consulto il registro locale.",
                          "get_current_datetime": "Controllo l'orario di Windows.",
                          "get_system_information": "Controllo le informazioni di Windows.",
                          "get_hardware_information": "Controllo l'hardware del computer.",
                          "get_memory_information": "Controllo la memoria disponibile.",
                          "get_disk_information": "Controllo lo spazio sui dischi.",
                          "get_battery_status": "Controllo l'alimentazione.",
                          "get_process_information": "Controllo i processi del tuo utente.",
                          "get_open_applications": "Controllo le applicazioni aperte.",
                          "list_applications": "Cerco le applicazioni installate.", "inspect_desktop": "Controllo le finestre.",
                          "inspect_files": "Leggo il percorso richiesto.", "open_resource": "Apro la destinazione richiesta.",
                          "desktop_action": "Interagisco con la finestra richiesta.", "run_powershell": "Eseguo il comando confermato."}
            intentions["start_autonomous_chat"] = "Avvio la conversazione autonoma autorizzata. Può interrompermi dicendo stop."
            intentions["run_research"] = "Avvio la ricerca autorizzata e preparo il PDF. Può interrompermi dicendo stop."
            intention = intentions.get(event.data["tool"], "Eseguo l'operazione autorizzata.")
            self.window.action_label.setText(intention)
            if not self.voice_turn or not self.speech.speak(intention):
                self._release_execution()
        elif event.kind == "approval":
            if self.closing or not self.worker or self.worker.cancellation.is_set():
                if self.worker:
                    self.worker.resolve_approval(event.data.request_id, False)
                return
            if event.data.call.name in {"start_autonomous_chat", "run_research"}:
                self.voice.monitor_stop()
            self.approval = ApprovalDialog(event.data, self.controller.settings.approval_timeout_seconds, self.window)
            self.overlay.dismiss()
            self.approval.decision.connect(self.worker.resolve_approval)
            self.approval.show()
            self.window.action_label.setText("In attesa della conferma per " + event.data.call.name)
        elif event.kind == "approval_closed":
            self._close_approval()

    def open_artifact(self):
        if self.artifact_path and self.artifact_path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.artifact_path)))

    def _close_approval(self) -> None:
        if self.approval is not None:
            self.approval.reject()
            self.approval.deleteLater()
            self.approval = None

    @Slot()
    def finished(self) -> None:
        self._close_approval()
        if not self.autonomy_active:
            self.voice.stop_monitoring()
        worker, self.worker = self.worker, None
        was_cancelled = bool(worker and worker.cancellation.is_set())
        if worker is not None:
            worker.deleteLater()
        self.window.set_busy(False)
        if self.model_status_dialog:
            self.model_status_dialog.refresh_button.setEnabled(True)
        if self.speech.active:
            self.window.stop_button.setEnabled(True)
        self.stream_timer.stop()
        self.window.set_stream("")
        if (self.voice_turn and self.had_error and not self.response_received and self.last_notice
                and not self.closing and not was_cancelled and not self.speech.active):
            self.speech.speak(spoken_reply(final_text(self.last_notice)))
        if not self.had_error and not self.speech.active:
            self.window.set_state("idle")
        if self.closing:
            self._finish_close()
        elif self.voice_turn and not self.speech.active:
            if self.had_error:
                self.voice.end_conversation()
            else:
                self.voice.complete_turn()
        elif not self.voice_turn and not self.speech.active and self.voice.enabled:
            self.voice.end_conversation()
        if self.probe_needed and not self.closing:
            self.probe_needed = False
            QTimer.singleShot(0, lambda: self.start({"kind": "provider_check"}))

    @Slot()
    def stop(self) -> None:
        self.voice_turn = False
        self.overlay_cycle = False
        self.autonomy_active = False
        self.window.allow_busy_input = False
        self.voice.stop_monitoring()
        if self.worker is not None:
            self.worker.cancel()
            self._close_approval()
            self.window.action_label.setText("Arresto richiesto. Le operazioni già completate non vengono annullate.")
        if self.voice.transcriber:
            self.voice.transcriber.cancel()
        self.speech.stop()
        self._release_execution()
        self.voice.end_conversation()
        self.overlay.dismiss()
        if self.worker is None:
            self.window.stop_button.setEnabled(False)

    @Slot()
    def close(self) -> None:
        self.closing = True
        self.stop()
        self.voice.shutdown()
        self.overlay.dismiss()
        if self.worker is not None:
            self.shutdown_timer.start()
        else:
            self._finish_close()

    def _finish_close(self):
        if self.worker is None and self.voice.is_stopped() and self.speech.is_stopped():
            self.shutdown_timer.stop()
            self.overlay.close()
            self.window.allow_close = True
            self.window.close()
        elif self.closing:
            self.shutdown_timer.start()

    @Slot()
    def show_model_status(self):
        if self.closing:
            return
        if self.model_status_dialog is None:
            from jarvis.ui.model_status import ModelStatusDialog
            self.model_status_dialog = ModelStatusDialog(self.window)
            self.model_status_dialog.refresh_requested.connect(self.refresh_model_status)
        if self.provider_info:
            self.model_status_dialog.set_status(self.provider_info)
        self.model_status_dialog.show()
        self.model_status_dialog.raise_()
        self.model_status_dialog.refresh_button.setEnabled(self.worker is None)
        self.refresh_model_status()

    @Slot()
    def refresh_model_status(self):
        if self.worker is None and not self.closing:
            self.start({"kind": "provider_check"})

    @Slot()
    def settings(self) -> None:
        if self.worker:
            return
        dialog = SettingsDialog(self.reduced_motion, self.log_level, self.window,
                                settings=self.controller.settings, voice=self.voice.settings, voices=self.speech.voices())
        dialog.reset_requested.connect(lambda: self.start({"kind": "reset_preferences"}))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            was_enabled = self.voice.enabled
            self.voice.disable()
            values = asdict(self.voice.settings)
            values.update(microphone_id=dialog.microphone.currentData() or "", voice_name=dialog.voice.currentText(),
                          sensitivity=dialog.sensitivity.value(), conversation_seconds=dialog.conversation.value(),
                          continuous_conversation=dialog.continuous.isChecked())
            self.start({"kind": "preferences", "reduced_motion": dialog.motion.isChecked(),
                        "log_level": dialog.level.currentText(), "voice": values})
            if was_enabled:
                self.window.microphone_label.setText("Microfono OFF · riattivalo per applicare i nuovi parametri")
        dialog.deleteLater()

    @Slot()
    def activities(self) -> None:
        if self.activity_dialog is None:
            self.activity_dialog = ActivityDialog(self.snapshot["tasks"], self.window)
        self.activity_dialog.set_tasks(self.snapshot["tasks"])
        self.activity_dialog.show()
        self.activity_dialog.raise_()

    def _flush_stream(self):
        self.window.set_stream("Verifica dell'esito prima della risposta finale…" if has_completion_claim(self.stream_buffer)
                               else final_text(self.stream_buffer))

    def _voice_state(self, state):
        if self.closing:
            return
        if state == "listening":
            if self.overlay_cycle:
                self.overlay.present("listening")
            self.window.set_state(state)
            self.window.stop_button.setEnabled(True)
        elif state == "thinking" and self.overlay_cycle:
            self.overlay.present("thinking", "Trascrizione locale…")
        elif state == "idle" and not self.speech.active and self.worker is None:
            self.overlay_cycle = False
            self.overlay.dismiss()
            self.window.set_state("idle")

    def _input_level(self, level):
        if self.voice.phase == "listening" and not self.speech.active:
            self.overlay.set_level(level)
            if hasattr(self.window.visualizer, "set_level"):
                self.window.visualizer.set_level(level)

    def _voice_command(self, text):
        if self.worker is None:
            self.start({"kind": "voice", "text": text})
        else:
            self.window.microphone_label.setText("Attività in corso: richiesta vocale non accodata")

    def toggle_microphone(self):
        if self.voice.enabled or self.voice.starting:
            if self.voice_turn:
                self.stop()
            self.voice.disable()
            self.overlay.dismiss()
        else:
            if self.autonomy_active:
                self.voice.control_only = True
            self.voice.enable()

    def listen(self):
        if self.worker:
            return
        if not self.voice.enabled:
            self.window.microphone_label.setText("Attiva prima il microfono, poi premi Ascolta o pronuncia «Jarvis»")
            return
        self._wake_activated()
        self.voice.listen()

    def _wake_activated(self):
        self.overlay_cycle = True
        self.actions_started = False
        self.overlay.present("listening")

    def repeat(self):
        if self.last_response:
            self.voice_turn = True
            self.speech.speak(spoken_reply(self.last_response))
        else:
            self.voice.complete_turn()

    def _speech_started(self):
        self.voice.set_playback(True)
        if self.overlay_cycle and not self.actions_started:
            self.overlay.present("speaking")
        self.window.set_state("speaking")
        self.window.stop_button.setEnabled(True)

    def _speech_finished(self):
        self.voice.set_playback(False)
        if self.execution_ack:
            self._release_execution()
        elif self.autonomy_active:
            self.voice.monitor_stop()
        elif self.worker is None and not self.closing:
            if self.voice_turn:
                self.overlay_cycle = False
                self.overlay.dismiss()
                self.voice.complete_turn()
            else:
                self.voice.end_conversation()
        if not self.voice.enabled or self.closing:
            self.overlay.dismiss()
        if self.worker is None and not self.voice.enabled:
            self.window.stop_button.setEnabled(False)
            self.window.set_state("idle")

    def _release_execution(self):
        self.overlay.dismiss()
        if self.execution_ack is not None:
            self.actions_started = True
            self.overlay_cycle = False
            ack, self.execution_ack = self.execution_ack, None
            ack.set()

    def _voice_error(self, message):
        self.window.microphone_label.setText(message)
        self._release_execution()
        if not self.closing and self.overlay_cycle:
            self.overlay.present("error", message)
