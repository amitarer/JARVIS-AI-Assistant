"""Start the local Ollama server and JARVIS without a console window."""

import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LOG_PATH = ROOT / "data/logs/startup.log"


def ollama_ready(url: str) -> bool:
    try:
        # Local requests must not be redirected through an inherited HTTP proxy.
        with build_opener(ProxyHandler({})).open(url.rstrip("/") + "/api/version", timeout=1) as response:
            return bool(json.load(response).get("version"))
    except (OSError, URLError, ValueError):
        return False


def ensure_ollama(settings, log) -> None:
    if not settings.enabled or ollama_ready(settings.url):
        return
    executable = shutil.which("ollama.exe")
    if not executable:
        for base, relative in (
            (os.environ.get("LOCALAPPDATA"), "Programs/Ollama/ollama.exe"),
            (os.environ.get("ProgramFiles"), "Ollama/ollama.exe"),
        ):
            if not base:
                continue
            candidate = Path(base) / relative
            if candidate.is_file():
                executable = str(candidate)
                break
    if not executable:
        raise RuntimeError(
            "Ollama non risponde e ollama.exe non e' stato trovato. "
            "Avvia Ollama oppure rendi disponibile la sua installazione nel PATH."
        )
    environment = os.environ.copy()
    environment["OLLAMA_HOST"] = urlsplit(settings.url).netloc
    print("Avvio Ollama in background...", flush=True)
    server = subprocess.Popen(
        [executable, "serve"],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if ollama_ready(settings.url):
            return
        if server.poll() is not None:
            raise RuntimeError("Ollama si e' chiuso durante l'avvio. Consulta il log di avvio.")
        time.sleep(0.5)
    raise RuntimeError("Ollama non risponde dopo 30 secondi. Consulta il log di avvio.")


def main() -> int:
    log = None
    original_stdout, original_stderr = sys.stdout, sys.stderr
    try:
        os.chdir(ROOT)
        from jarvis.bootstrap import ensure_local_data
        from jarvis.infrastructure.settings import load_settings

        settings = load_settings(ROOT)
        ensure_local_data(settings)
        log = LOG_PATH.open("a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
        print(time.strftime("\n[%Y-%m-%d %H:%M:%S] Avvio JARVIS"), flush=True)
        ensure_ollama(settings.ollama, log)
        from jarvis.__main__ import main as start_jarvis

        return start_jarvis()
    except Exception as exc:
        if log:
            traceback.print_exc(file=log)
            log.flush()
        ctypes.windll.user32.MessageBoxW(
            None,
            f"Impossibile avviare JARVIS.\n\n{exc}\n\nLog, se disponibile:\n{LOG_PATH}",
            "JARVIS - Avvio non riuscito",
            0x10,
        )
        return 1
    finally:
        sys.stdout, sys.stderr = original_stdout, original_stderr
        if log:
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
