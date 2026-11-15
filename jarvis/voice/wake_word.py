"""Custom openWakeWord ONNX validation and bounded, CPU-only streaming inference."""

import hashlib
import queue
import threading
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QThread, Signal

MODEL_NAME = "Jarvis_20260313_215039"


def local_model(root: Path, relative: str) -> Path:
    candidate = root / relative
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file() or candidate.is_symlink():
        raise ValueError("Modello wake word assente o fuori dal progetto.")
    return resolved


def inspect_classifier(path: Path) -> dict:
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
    inputs, outputs = session.get_inputs(), session.get_outputs()
    if (len(inputs) != 1 or len(outputs) != 1 or inputs[0].type != "tensor(float)"
            or len(inputs[0].shape) != 3 or inputs[0].shape[1:] != [16, 96]
            or inputs[0].shape[0] not in {1, None, 'batch_size', 'batch'}
            or outputs[0].type != "tensor(float)"):
        raise ValueError("Il modello non è un classificatore openWakeWord [1,16,96] float32 compatibile.")
    result = session.run(None, {inputs[0].name: np.zeros((1, 16, 96), np.float32)})[0]
    if result.shape != (1, 1) or not np.isfinite(result).all() or not 0 <= result.item() <= 1:
        raise ValueError("Il modello non restituisce una probabilità valida [1,1].")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "input": inputs[0].shape, "output": outputs[0].shape,
            "zero_score": float(result.item()), "structurally_compatible": True}


def create_detector(root: Path, relative: str):
    from openwakeword.model import Model
    path = local_model(root, relative)
    inspect_classifier(path)
    shared = root / "data/models/openwakeword"
    for filename in ("melspectrogram.onnx", "embedding_model.onnx"):
        local_model(root, str(shared / filename))
    return Model(wakeword_models=[str(path)], inference_framework="onnx", ncpu=1,
                 melspec_model_path=str(shared / "melspectrogram.onnx"),
                 embedding_model_path=str(shared / "embedding_model.onnx"))


class ActivationGate:
    def __init__(self, sensitivity: float, cooldown: float = 2.0):
        self.threshold = max(0.05, min(0.9, 1 - sensitivity))
        self.cooldown = cooldown
        self.last_detection = float('-inf')
        self.consecutive = 0
        self.last_voice = float('-inf')

    def reset(self):
        self.consecutive = 0
        self.last_voice = float('-inf')

    def feed(self, score: float, energy: float, now: float) -> bool:
        if not np.isfinite(score) or not np.isfinite(energy):
            self.reset()
            return False
        if energy >= 0.002:
            self.last_voice = now
        # The classifier sees a history of audio: its peak can arrive after the syllable ends.
        if now - self.last_voice > 0.8 or now - self.last_detection < self.cooldown:
            self.consecutive = 0
            return False
        self.consecutive = self.consecutive + 1 if score >= self.threshold else 0
        strong_match = score >= max(0.3, min(0.98, self.threshold * 1.8))
        if self.consecutive >= 2 or strong_match:
            self.last_detection, self.consecutive = now, 0
            return True
        return False


class WakeWorker(QThread):
    ready = Signal()
    detected = Signal(float)
    score = Signal(float)
    error = Signal(str)

    def __init__(self, root: Path, settings, parent=None):
        super().__init__(parent)
        self.root, self.settings = root, settings
        self.queue = queue.Queue(maxsize=24)
        self.stopping = threading.Event()
        self.suspended = threading.Event()
        self.reset_requested = threading.Event()
        self.gate = ActivationGate(settings.sensitivity)
        self.model_ready = False
        self.processed_frames = 0
        self.last_score = self.peak_score = 0.0
        self.energy_at_peak = 0.0
        self.detections = 0
        self.last_error = ""

    def feed(self, samples):
        if self.stopping.is_set() or self.suspended.is_set():
            return
        try:
            self.queue.put_nowait(samples.copy())
        except queue.Full:
            # Discard stale audio and reset the feature stream on overflow.
            self.flush()

    def flush(self):
        self.reset_requested.set()
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                return

    def stop(self):
        self.stopping.set()
        self.flush()

    def run(self):
        try:
            detector = create_detector(self.root, self.settings.model_path)
            self.model_ready = True
            self.ready.emit()
            pending = np.empty(0, np.int16)
            was_suspended = False
            while not self.stopping.is_set():
                if self.suspended.is_set():
                    pending = np.empty(0, np.int16)
                    was_suspended = True
                    self.stopping.wait(0.04)
                    continue
                if was_suspended:
                    detector.reset()
                    self.gate.reset()
                    was_suspended = False
                if self.reset_requested.is_set():
                    detector.reset()
                    self.gate.reset()
                    pending = np.empty(0, np.int16)
                    self.reset_requested.clear()
                try:
                    samples = self.queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                pending = np.concatenate((pending, samples))
                while pending.size >= 1280 and not self.suspended.is_set() and not self.stopping.is_set():
                    frame, pending = pending[:1280], pending[1280:]
                    prediction = detector.predict(frame)
                    score = float(next(iter(prediction.values())))
                    self.score.emit(score)
                    energy = float(np.sqrt(np.mean((frame.astype(np.float32) / 32768) ** 2)))
                    self.processed_frames += 1
                    self.last_score = score
                    if score > self.peak_score:
                        self.peak_score, self.energy_at_peak = score, energy
                    if self.gate.feed(score, energy, time.monotonic()):
                        self.detections += 1
                        self.suspended.set()
                        self.detected.emit(score)
                        break
        except Exception as exc:
            self.last_error = type(exc).__name__ + ": " + str(exc)[:300]
            self.error.emit("Wake word non disponibile (" + self.last_error + ").")
        finally:
            self.model_ready = False
