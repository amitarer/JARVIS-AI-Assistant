"""Explicit model downloads. Runtime inference never downloads or executes remote code."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def wake_models():
    folder = ROOT / "data/models/openwakeword"
    folder.mkdir(parents=True, exist_ok=True)
    records = {}
    for filename in ("melspectrogram.onnx", "embedding_model.onnx"):
        path = folder / filename
        url = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/" + filename
        if not path.exists():
            temporary = path.with_suffix(".download")
            print("Download:", filename, flush=True)
            with urllib.request.urlopen(url, timeout=30) as response, temporary.open('wb') as output:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > 100_000_000:
                        raise RuntimeError("Modello condiviso oltre il limite previsto.")
                    output.write(chunk)
            temporary.replace(path)
        records[filename] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "source": url}
    (folder / "manifest.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print("Backbone openWakeWord disponibili nel progetto.", flush=True)


def stt_model():
    cache = ROOT / "data/cache/huggingface"
    os.environ["HF_HOME"] = str(cache)
    os.environ["HF_XET_CACHE"] = str(cache / "xet")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    from huggingface_hub import HfApi, snapshot_download
    revision = HfApi().model_info("Systran/faster-whisper-small").sha
    print("Download STT italiano: faster-whisper-small, revisione", revision, flush=True)
    folder = ROOT / "data/models/whisper-small"
    snapshot_download("Systran/faster-whisper-small", revision=revision, local_dir=str(folder),
                      cache_dir=str(cache / "hub"), allow_patterns=["model.bin", "config.json", "tokenizer.json", "vocabulary.*", "preprocessor_config.json"])
    (folder / "revision.txt").write_text(revision, encoding="utf-8")
    print("Modello STT disponibile nel progetto.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wake-only", action="store_true")
    parser.add_argument("--stt-only", action="store_true")
    args = parser.parse_args()
    if not args.stt_only:
        wake_models()
    if not args.wake_only:
        stt_model()
