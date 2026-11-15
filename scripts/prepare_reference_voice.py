"""Prepare audition samples with the existing voice; no install or voice cloning."""

import base64
import io
import json
import os
from pathlib import Path
import subprocess
import wave


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = {
    "cosimo_neutro": "Buongiorno, signore. Sono Jarvis. Ho preparato la risposta. Può leggerla prima dell’invio. Attendo la sua conferma.",
    "cosimo_operativo": "Ho completato la verifica nella finestra di prova. Il risultato è disponibile. Desidera continuare?",
}


def main():
    folder = ROOT / "data/voice-reference"
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"voice": "Microsoft Cosimo", "engine": "existing Windows WinRT",
                "active_voice_changed": False, "cloned_reference_voice": False,
                "sample_purpose": "Audition only, prerecorded synthetic phrases are not assistant task results.",
                "samples": []}
    executable = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    for name, text in SAMPLES.items():
        result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                 "-File", str(ROOT / "scripts/synthesize_windows.ps1")],
                                input=json.dumps({"text": text, "voice": "Microsoft Cosimo", "allow_fallback": False}).encode("ascii"),
                                capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError("Sintesi del campione Windows non riuscita.")
        response = json.loads(result.stdout.decode("utf-8-sig"))
        data = base64.b64decode(response["wav"], validate=True)
        with wave.open(io.BytesIO(data), "rb") as wav:
            entry = {"file": name + ".wav", "text": text, "rate": wav.getframerate(),
                     "channels": wav.getnchannels(), "bits": wav.getsampwidth() * 8,
                     "seconds": round(wav.getnframes() / wav.getframerate(), 3)}
        (folder / entry["file"]).write_bytes(data)
        manifest["samples"].append(entry)
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
