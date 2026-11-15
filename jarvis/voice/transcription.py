"""Persistent, single-job local STT worker. Never downloads models at runtime."""

import queue
import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import QThread, Signal


def transcription_options(root):
    from jarvis.tools.websites import WebsiteCatalog
    from jarvis.infrastructure.settings import load_settings
    applications = load_settings(root).applications
    hints = ["Jarvis", "Chrome", *[app.label for app in applications.values()]]
    for site in WebsiteCatalog(root).entries():
        hints.extend([site["label"], site["host"]])
    hotwords = ", ".join(dict.fromkeys(hints))[:1000]
    return {"language": "it", "beam_size": 5, "vad_filter": True, "condition_on_previous_text": False,
            "hotwords": hotwords,
            "initial_prompt": "Comandi in italiano, con nomi propri di applicazioni e siti: " + hotwords,
            "vad_parameters": {"min_silence_duration_ms": 500}}


class TranscriptionWorker(QThread):
    text = Signal(str, int)
    error = Signal(str, int)

    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = root
        self.jobs = queue.Queue(maxsize=1)
        self.stopping = threading.Event()
        self.cancelled = threading.Event()

    def submit(self, samples, generation: int, *, control_only=False):
        self.cancelled.clear()
        try:
            self.jobs.put_nowait((samples.copy(), generation, control_only))
        except queue.Full:
            self.error.emit("Trascrizione già in corso.", generation)

    def cancel(self):
        self.cancelled.set()
        while True:
            try:
                self.jobs.get_nowait()
            except queue.Empty:
                break

    def stop(self):
        self.stopping.set()
        self.cancel()

    def run(self):
        model = None
        while not self.stopping.is_set():
            try:
                samples, generation, control_only = self.jobs.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                folder = self.root / "data/models/whisper-small"
                if not (folder / "model.bin").is_file():
                    raise FileNotFoundError
                if model is None:
                    from faster_whisper import WhisperModel
                    model = WhisperModel(str(folder), device="cpu", compute_type="int8", cpu_threads=4,
                                         num_workers=1, local_files_only=True)
                if self.cancelled.is_set() or self.stopping.is_set():
                    continue
                options = transcription_options(self.root)
                if control_only:
                    options.update(beam_size=1, initial_prompt="Stop. Fermati. Basta.", hotwords="stop, fermati, basta",
                                   vad_parameters={"min_silence_duration_ms": 200})
                segments, _ = model.transcribe(samples.astype(np.float32) / 32768, **options)
                parts = []
                for segment in segments:
                    if self.cancelled.is_set() or self.stopping.is_set():
                        break
                    if segment.no_speech_prob < 0.6:
                        parts.append(segment.text)
                if not self.cancelled.is_set() and not self.stopping.is_set():
                    self.text.emit(" ".join(parts).strip(), generation)
            except FileNotFoundError:
                self.error.emit("Modello STT assente. Esegui scripts/setup_voice_models.py prima della conversazione vocale.", generation)
            except Exception as exc:
                self.error.emit("Trascrizione locale non riuscita (" + type(exc).__name__ + ").", generation)
