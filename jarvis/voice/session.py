"""Wake/listen/transcribe state machine with half-duplex echo exclusion."""

import re
import time
from collections import deque

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from jarvis.voice.audio import AudioInput
from jarvis.voice.transcription import TranscriptionWorker
from jarvis.voice.wake_word import WakeWorker


def spoken_control(text: str) -> str | None:
    words = re.sub(r"[^\w\s]", " ", text.casefold()).split()
    if words and words[0] in {"jarvis", "jervis"}:
        words = words[1:]
    if " ".join(words) in {"no", "no grazie", "basta", "grazie", "nient altro", "niente altro", "nulla", "non serve altro"}:
        return "chiudi"
    return words[0] if len(words) == 1 and words[0] in {"stop", "fermati", "annulla", "chiudi", "ripeti"} else None


class VoiceSession(QObject):
    command = Signal(str)
    state = Signal(str)
    status = Signal(str)
    level = Signal(float)
    error = Signal(str)
    activated = Signal()
    stopped = Signal()
    repeat = Signal()
    enabled_changed = Signal(bool)
    score = Signal(float)

    def __init__(self, root, settings, parent=None):
        super().__init__(parent)
        self.root, self.settings = root, settings
        self.audio = AudioInput(self)
        self.audio.frames.connect(self._frames)
        self.audio.level.connect(self.level)
        self.audio.error.connect(self._error)
        self.wake = None
        self.transcriber = None
        self.enabled = self.starting = self.playback = False
        self.phase = "off"
        self.control_only = False
        self.generation = 0
        self.resume_after = 0.0
        self.deadline = 0.0
        self.noise = 0.002
        self.parts = []
        self.preroll = deque()
        self.preroll_samples = 0
        self.speech_samples = self.total_samples = 0
        self.last_voice = self.listen_started = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)

    def enable(self):
        if self.enabled or self.starting:
            return
        if self.wake is not None:
            self.status.emit("Attendi la chiusura del motore vocale precedente.")
            return
        self.starting = True
        self.phase = "starting"
        self.status.emit("Caricamento modello Jarvis locale…")
        self.wake = WakeWorker(self.root, self.settings, self)
        self.wake.ready.connect(self._ready)
        self.wake.detected.connect(self._wake)
        self.wake.score.connect(self.score)
        self.wake.error.connect(self._error)
        self.wake.finished.connect(self._wake_finished)
        self.wake.start()

    def _ready(self):
        if not self.starting:
            return
        try:
            self.audio.start(self.settings.microphone_id)
        except Exception as exc:
            self._error(str(exc))
            return
        self.starting = False
        self.enabled = True
        self.phase = "wake"
        self._prepare_transcriber()
        self.enabled_changed.emit(True)
        self.status.emit("Microfono ON · in attesa di «Jarvis»")
        self.timer.start()
        if self.control_only:
            self.monitor_stop()

    def _wake_finished(self):
        if self.wake:
            self.wake.deleteLater()
            self.wake = None

    def _wake(self, score=0.0):
        if not self.enabled or self.playback or self.phase != "wake":
            return
        self.activated.emit()
        self.listen(include_preroll=True)

    def listen(self, *, include_preroll=False):
        if not self.enabled or self.playback:
            return
        if self.wake:
            self.wake.suspended.set()
            self.wake.flush()
        self.phase = "listening"
        self.parts = list(self.preroll) if include_preroll else []
        self.total_samples = sum(part.size for part in self.parts)
        self.speech_samples = sum(part.size for part in self.parts if float(np.sqrt(np.mean((part.astype(np.float32) / 32768) ** 2))) > max(0.0015, self.noise * 2.5))
        self.preroll.clear()
        self.preroll_samples = 0
        self.last_voice = self.listen_started = time.monotonic()
        self.deadline = time.monotonic() + self.settings.conversation_seconds
        self.state.emit("listening")
        self.status.emit("Microfono ON · ti ascolto")

    def _frames(self, samples):
        if not self.enabled or self.playback or time.monotonic() < self.resume_after:
            return
        if self.phase == "wake":
            chunk = samples[-12800:].copy()
            self.preroll.append(chunk)
            self.preroll_samples += chunk.size
            while self.preroll_samples > 12800 and len(self.preroll) > 1:
                self.preroll_samples -= self.preroll.popleft().size
            rms = float(np.sqrt(np.mean((samples.astype(np.float32) / 32768) ** 2)))
            if rms < self.noise * 2:
                self.noise = self.noise * 0.98 + rms * 0.02
            if self.wake:
                self.wake.feed(samples)
        elif self.phase in {"listening", "control"}:
            self.parts.append(samples)
            self.total_samples += samples.size
            rms = float(np.sqrt(np.mean((samples.astype(np.float32) / 32768) ** 2)))
            if rms > max(0.0015, self.noise * 2.5):
                self.speech_samples += samples.size
                self.last_voice = time.monotonic()
                self.deadline = self.last_voice + self.settings.conversation_seconds
            maximum = 2 if self.control_only else self.settings.max_utterance_seconds
            if self.total_samples >= maximum * 16000:
                self._transcribe()
            elif not self.speech_samples and self.total_samples > 16000:
                self.parts = [samples]
                self.total_samples = samples.size

    def _tick(self):
        now = time.monotonic()
        if self.phase in {"listening", "control"}:
            silence = 0.3 if self.control_only else self.settings.silence_seconds
            if self.speech_samples >= 2400 and now - self.last_voice >= silence:
                self._transcribe()
            elif not self.control_only and now >= self.deadline:
                self.end_conversation()

    def _transcribe(self):
        if not self.parts:
            return
        if self.speech_samples < 2400:
            self.monitor_stop() if self.control_only else self.listen()
            return
        self.phase = "control_processing" if self.control_only else "processing"
        if not self.control_only:
            self.state.emit("thinking")
            self.status.emit("Microfono ON · trascrizione locale")
        self._prepare_transcriber()
        self.transcriber.submit(np.concatenate(self.parts), self.generation, control_only=self.control_only)
        self.parts = []

    def _prepare_transcriber(self):
        if self.transcriber is None:
            self.transcriber = TranscriptionWorker(self.root, self)
            self.transcriber.text.connect(self._text)
            self.transcriber.error.connect(self._transcription_error)
            self.transcriber.start()

    def _text(self, text, generation):
        if generation != self.generation or not self.enabled:
            return
        control = spoken_control(text)
        if self.control_only:
            if control in {"stop", "fermati", "annulla", "chiudi"}:
                self.stopped.emit()
            else:
                self.monitor_stop()
            return
        if control in {"stop", "fermati", "annulla"}:
            self.stopped.emit()
            self.end_conversation()
        elif control == "chiudi":
            self.end_conversation()
        elif control == "ripeti":
            self.repeat.emit()
        else:
            text = re.sub(r"^(?:jarvis|jervis)[\s,.:;!?]*", "", text.strip(), flags=re.IGNORECASE)
            if text:
                self.command.emit(text)
            else:
                self.activated.emit()
                self.listen()

    def _transcription_error(self, message, generation):
        if generation == self.generation and self.enabled:
            self.error.emit(message)
            self.monitor_stop() if self.control_only else self.end_conversation()

    def monitor_stop(self):
        if not self.control_only:
            self.generation += 1
            if self.transcriber:
                self.transcriber.cancel()
        self.control_only = True
        if not self.enabled or self.playback:
            return
        if self.wake:
            self.wake.suspended.set()
            self.wake.flush()
        self.phase = "control"
        self.parts = []
        self.total_samples = self.speech_samples = 0
        self.last_voice = self.listen_started = time.monotonic()
        self.status.emit("Microfono ON · attività autonoma · pronuncia STOP per interrompere")

    def stop_monitoring(self):
        if self.control_only:
            self.control_only = False
            if self.transcriber:
                self.transcriber.cancel()
            self.end_conversation()

    def set_playback(self, playing: bool):
        self.playback = playing
        if self.wake:
            self.wake.suspended.set()
            self.wake.flush()
        self.parts = []
        self.preroll.clear()
        self.preroll_samples = 0
        if playing:
            self.phase = "speaking" if self.enabled else "off"
        else:
            self.resume_after = time.monotonic() + 0.5

    def complete_turn(self):
        if self.enabled and not self.playback:
            if self.settings.continuous_conversation:
                self.listen()
            else:
                self.end_conversation()

    def pause_for_task(self):
        if self.enabled:
            self.phase = "processing"
            self.parts = []
            if self.wake:
                self.wake.suspended.set()
                self.wake.flush()

    def end_conversation(self):
        self.parts = []
        self.preroll.clear()
        self.preroll_samples = 0
        self.generation += 1
        self.phase = "wake" if self.enabled else "off"
        self.resume_after = time.monotonic() + 0.5
        if self.wake and self.enabled and not self.playback:
            self.wake.flush()
            self.wake.suspended.clear()
        self.state.emit("idle")
        self.status.emit("Microfono ON · in attesa di «Jarvis»" if self.enabled else "Microfono OFF")

    def disable(self):
        self.control_only = False
        self.starting = self.enabled = False
        self.generation += 1
        self.timer.stop()
        self.audio.stop()
        self.parts = []
        self.preroll.clear()
        self.preroll_samples = 0
        if self.wake:
            self.wake.stop()
        if self.transcriber:
            self.transcriber.cancel()
        self.phase = "off"
        self.enabled_changed.emit(False)
        self.state.emit("idle")
        self.status.emit("Microfono OFF · acquisizione arrestata")

    def _error(self, message):
        self.disable()
        self.error.emit(message)

    def shutdown(self):
        self.disable()
        if self.transcriber:
            self.transcriber.stop()

    def is_stopped(self):
        return (self.wake is None or not self.wake.isRunning()) and (self.transcriber is None or not self.transcriber.isRunning())
