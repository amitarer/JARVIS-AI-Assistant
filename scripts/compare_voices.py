"""Generate Windows voice samples and an objective PCM report without installing anything."""

import base64
import io
import json
from pathlib import Path
import subprocess
import sys
import wave

import numpy as np
from PySide6.QtMultimedia import QAudioFormat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jarvis.voice.pcm import decode_pcm, output_pcm

PHRASE = "Buongiorno, Gae. Sono Jarvis, il tuo assistente personale. Tutti i sistemi sono operativi. Come posso aiutarti?"


def generate():
    folder = ROOT / "data/voice-comparison"
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    for slug, name, gender in (("cosimo", "Microsoft Cosimo", "maschile"), ("elsa", "Microsoft Elsa", "femminile · riferimento")):
        process = subprocess.run(["C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", "-NoProfile", "-NonInteractive",
                                  "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts/synthesize_windows.ps1")],
                                 input=json.dumps({"text": PHRASE, "voice": name, "allow_fallback": False}).encode('ascii'),
                                 capture_output=True, timeout=20)
        if process.returncode:
            raise RuntimeError("Impossibile generare il campione " + name)
        response = json.loads(process.stdout.decode('utf-8-sig'))
        wav = base64.b64decode(response["wav"], validate=True)
        original = folder / f"{slug}_originale.wav"
        original.write_bytes(wav)
        with wave.open(io.BytesIO(wav), 'rb') as stream:
            rate, channels, width = stream.getframerate(), stream.getnchannels(), stream.getsampwidth()
            data = stream.readframes(stream.getnframes())
        if width != 2:
            raise ValueError("Il campione Windows non è PCM16.")
        source = QAudioFormat()
        source.setSampleRate(rate)
        source.setChannelCount(channels)
        source.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        target = QAudioFormat()
        target.setSampleRate(48000)
        target.setChannelCount(2)
        target.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        converted = output_pcm(data, source, target)
        prepared = folder / f"{slug}_48k.wav"
        with wave.open(str(prepared), 'wb') as stream:
            stream.setframerate(48000)
            stream.setnchannels(2)
            stream.setsampwidth(2)
            stream.writeframes(converted)
        raw, fixed = decode_pcm(data, source), decode_pcm(converted, target)
        entry = {"name": name, "gender": gender, "original": original.name, "prepared": prepared.name,
                 "source_rate": rate, "source_channels": channels, "source_bits": width * 8,
                 "duration_seconds": len(raw) / rate, "prepared_duration_seconds": len(fixed) / 48000,
                 "source_peak_dbfs": float(20 * np.log10(max(float(np.abs(raw).max()), 1e-12))),
                 "source_clipped_samples": int(np.sum(np.abs(raw) >= 32767 / 32768)),
                 "prepared_peak_dbfs": float(20 * np.log10(max(float(np.abs(fixed).max()), 1e-12))),
                 "prepared_clipped_samples": int(np.sum(np.abs(fixed) >= 32767 / 32768))}
        entries.append(entry)
        print(json.dumps(entry, ensure_ascii=True), flush=True)
    manifest = {"phrase": PHRASE, "engine": "Windows WinRT SpeechSynthesizer", "rate": "naturale, nessun rallentamento",
                "pitch": "originale", "active_voice_changed": False, "samples": entries}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    generate()
