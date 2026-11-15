"""Exercise real local wake/STT models with silent synthetic Windows speech."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtMultimedia import QAudioFormat

from jarvis.infrastructure.settings import load_settings
from jarvis.brain.ollama import OllamaProvider
from jarvis.core.tasks import TaskContext
from jarvis.tools.pc import OpenResourceTool
from jarvis.tools.websites import WebsiteCatalog
import threading
from jarvis.voice.audio import PcmConverter
from jarvis.voice.replies import spoken_reply
from jarvis.voice.transcription import TranscriptionWorker
from jarvis.voice.wake_word import ActivationGate, create_detector
from jarvis.voice.windows_synthesis import WindowsSynthesis


def synthesize(text):
    captured, errors = [], []
    worker = WindowsSynthesis(text, "Microsoft Cosimo", True)
    worker.audio.connect(lambda pcm, rate, channels, width: captured.append((pcm, rate, channels, width)))
    worker.error.connect(errors.append)
    worker.run()
    if not captured:
        raise RuntimeError("Sintesi locale di prova non disponibile: " + "; ".join(errors))
    pcm, rate, channels, width = captured[0]
    if width != 2:
        raise RuntimeError("Formato di sintesi di prova inatteso.")
    return PcmConverter(rate, channels, QAudioFormat.SampleFormat.Int16).convert(pcm)


def main():
    app = QCoreApplication([])
    settings = load_settings(ROOT)
    report = {"sample_source": "Windows Cosimo synthetic speech, not played aloud", "human_voice_tested": False,
              "microphone_used": False, "passed": False}
    detector = create_detector(ROOT, settings.voice.model_path)
    gate = ActivationGate(0.95)
    samples = np.concatenate((np.zeros(32000, np.int16), synthesize("Jarvis."), np.zeros(32000, np.int16)))
    peak, detected = 0.0, False
    for offset in range(0, len(samples) - 1279, 1280):
        frame = samples[offset:offset + 1280]
        score = float(next(iter(detector.predict(frame).values())))
        peak = max(peak, score)
        detected |= gate.feed(score, float(np.sqrt(np.mean((frame.astype(np.float32) / 32768) ** 2))), offset / 16000)
    report.update(wake_peak=peak, wake_detected=bool(detected))
    transcription = TranscriptionWorker(ROOT)
    def receive(text, generation):
        report["transcription"] = text
        transcription.stop()
        app.quit()
    def error(message, generation):
        report["error"] = message
        transcription.stop()
        app.quit()
    transcription.text.connect(receive)
    transcription.error.connect(error)
    transcription.start()
    transcription.submit(synthesize("Apri ChatGPT punto com."), 1)
    QTimer.singleShot(30000, app.quit)
    app.exec()
    transcription.stop()
    transcription.wait(15000)
    report["spoken_follow_up"] = spoken_reply("Apertura richiesta.")
    text = report.get("transcription", "")
    resource = OpenResourceTool(WebsiteCatalog(ROOT))
    schemas = [{"name": resource.name, "description": resource.description, "parameters": resource.parameters},
               {"name": "get_current_datetime", "description": "Orologio Windows", "parameters": {"type": "object", "properties": {}}}]
    calls = OllamaProvider(settings.ollama).select_initial_tools(
        [{"role": "user", "content": text}], schemas, TaskContext("synthetic-voice-url", threading.Event(), 30))
    if len(calls) == 1 and calls[0].name == "open_resource":
        target = resource.validate(json.loads(calls[0].arguments_json))["target"]
        report["resolved_target"] = target
    report["passed"] = bool(detected and report.get("resolved_target") == "https://chatgpt.com/")
    folder = ROOT / "data/verification"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "voice-followup.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
