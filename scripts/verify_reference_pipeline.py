"""Real synthetic speech -> wake/STT -> Qwen -> Windows clock -> response PCM.

No microphone, playback, email, desktop mutation or production database access.
Synthetic input verifies the local pipeline, not the user's voice or acoustics.
"""

from dataclasses import replace
import json
from pathlib import Path
import secrets
import sys
import threading
import time
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6.QtCore import QCoreApplication
from PySide6.QtMultimedia import QAudioFormat
from faster_whisper import WhisperModel

from jarvis.brain.ollama import OllamaProvider
from jarvis.core.controller import Controller
from jarvis.infrastructure.settings import load_settings
from jarvis.infrastructure.system_information import SystemInformation
from jarvis.memory.database import Database
from jarvis.memory.repository import Repository
from jarvis.security.approvals import ApprovalStore
from jarvis.security.policy import SecurityPolicy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.system_information import SystemInformationTool
from jarvis.voice.audio import PcmConverter
from jarvis.voice.wake_word import ActivationGate, create_detector
from jarvis.voice.windows_synthesis import WindowsSynthesis


def synthesize(text):
    captured, errors = [], []
    worker = WindowsSynthesis(text, "Microsoft Cosimo", False)
    worker.audio.connect(lambda *values: captured.append(values))
    worker.error.connect(errors.append)
    worker.run()
    if not captured:
        raise RuntimeError("Sintesi locale non riuscita: " + "; ".join(errors))
    pcm, rate, channels, width = captured[0]
    if width != 2:
        raise ValueError("Il campione deve essere PCM16.")
    samples = PcmConverter(rate, channels, QAudioFormat.SampleFormat.Int16).convert(pcm)
    return samples, (pcm, rate, channels, width)


def main():
    app = QCoreApplication([])
    folder = ROOT / "data/verification/reference-video"
    folder.mkdir(parents=True, exist_ok=True)
    settings = load_settings(ROOT)
    settings = replace(settings, ollama=replace(settings.ollama, timeout_seconds=60))
    report = {"input": "locally synthesized Cosimo speech", "microphone_used": False,
              "human_voice_verified": False, "playback_used": False, "checks": {}, "errors": []}
    started = time.monotonic()
    try:
        samples, _ = synthesize("Jarvis.")
        padded = np.concatenate((np.zeros(32000, np.int16), samples, np.zeros(32000, np.int16)))
        detector = create_detector(ROOT, settings.voice.model_path)
        gate = ActivationGate(settings.voice.sensitivity)
        peak, detected = 0.0, False
        for offset in range(0, len(padded) - 1279, 1280):
            frame = padded[offset:offset + 1280]
            score = float(next(iter(detector.predict(frame).values())))
            peak = max(peak, score)
            energy = float(np.sqrt(np.mean((frame.astype(np.float32) / 32768) ** 2)))
            detected |= gate.feed(score, energy, offset / 16000)
        report["wake_peak"] = peak
        report["checks"]["synthetic_jarvis_detected"] = bool(detected)
        samples, _ = synthesize("Che ore sono?")
        model = WhisperModel(str(ROOT / "data/models/whisper-small"), device="cpu", compute_type="int8",
                             cpu_threads=4, num_workers=1, local_files_only=True)
        stt_started = time.monotonic()
        segments, _ = model.transcribe(samples.astype(np.float32) / 32768, language="it", beam_size=5,
                                       vad_filter=True, condition_on_previous_text=False)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        report["transcription"] = text
        report["stt_seconds"] = round(time.monotonic() - stt_started, 3)
        report["checks"]["actual_stt_nonempty"] = bool(text)
        database = Database(folder / f"voice-clock-{secrets.token_hex(4)}.sqlite3")
        database.initialize()
        repository = Repository(database)
        registry = ToolRegistry(SecurityPolicy(ApprovalStore()))
        registry.register(SystemInformationTool(SystemInformation(), "get_current_datetime"))
        controller = Controller(settings, repository, registry)
        events = []
        original = OllamaProvider.select_initial_tools

        def track_selector(self, messages, schemas, context):
            # Instrument the actual HTTP implementation; no fixture model response.
            calls = original(self, messages, schemas, context)
            report["selected_tools"] = [call.name for call in calls]
            return calls

        ai_started = time.monotonic()
        with patch.object(OllamaProvider, "select_initial_tools", track_selector):
            controller.run({"kind": "voice", "text": text}, threading.Event(), events.append,
                           lambda *_: None)
        report["ai_and_windows_seconds"] = round(time.monotonic() - ai_started, 3)
        answers = [event.data for event in events if event.kind == "response"]
        answer = answers[-1] if answers else ""
        operations = repository.operations()
        report["operations"] = [{"tool": row["tool"], "status": row["status"]} for row in operations]
        report["answer"] = answer
        report["model"] = settings.ollama.model
        report["checks"]["qwen_selected_real_clock_tool"] = report.get("selected_tools") == ["get_current_datetime"]
        report["checks"]["windows_observation_audited"] = len(operations) == 1 and operations[0]["status"] == "succeeded"
        report["checks"]["only_final_text_for_tts"] = bool(answer) and "<think" not in answer.casefold()
        if answer:
            tts_started = time.monotonic()
            _, (pcm, rate, channels, width) = synthesize(answer)
            with wave.open(str(folder / "clock-response.wav"), "wb") as wav:
                wav.setnchannels(channels)
                wav.setsampwidth(width)
                wav.setframerate(rate)
                wav.writeframes(pcm)
            report["tts_seconds"] = round(time.monotonic() - tts_started, 3)
            report["reply_pcm_bytes"] = len(pcm)
            report["checks"]["actual_response_pcm_produced"] = len(pcm) > 1000
        else:
            report["checks"]["actual_response_pcm_produced"] = False
        report["notices"] = [event.data for event in events if event.kind == "notice"]
    except Exception as exc:
        report["errors"].append(type(exc).__name__ + ": " + str(exc))
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    report["passed"] = len(report["checks"]) == 6 and all(report["checks"].values()) and not report["errors"]
    (folder / "pipeline-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
