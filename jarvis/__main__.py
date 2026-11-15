"""Project-local command line entrypoints."""

import argparse
import sys
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="JARVIS desktop assistant")
    parser.add_argument("--voice-test", action="store_true", help="Test microfono Jarvis + overlay + voce Windows, senza AI")
    parser.add_argument("--voice-compare", action="store_true", help="Ascolta campioni locali senza cambiare la voce attiva")
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--dashboard", dest="dashboard", action="store_true", help="Mostra la finestra principale all'avvio")
    display.add_argument("--background", dest="dashboard", action="store_false", help="Avvia nel tray senza mostrare la finestra")
    parser.set_defaults(dashboard=None)
    parser.add_argument("--no-microphone", action="store_true", help="Avvia con acquisizione audio disabilitata")
    parser.add_argument("--status", action="store_true", help="Mostra lo stato reale di microfono e wake word, senza audio registrato")
    parser.add_argument("--neural-preview", action="store_true", help="Anteprima 3D isolata, senza Ollama o microfono")
    parser.add_argument("--neural-particles", type=int, default=4800, choices=range(400, 6001), metavar="400..6000")
    parser.add_argument("--neural-style", choices=("organic", "cortex"), default="organic", help="Nucleo ambra dal riferimento o corteccia ciano")
    parser.add_argument("--neural-pixel-ratio", type=float, default=1.5, choices=(0.75, 1.0, 1.25, 1.5, 2.0))
    parser.add_argument("--neural-fps", type=int, default=60, choices=(24, 30, 60))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    if sys.version_info[:2] != (3, 12) or Path(sys.prefix).resolve() != (root / ".venv").resolve():
        print("Usa .venv\\Scripts\\python.exe -m jarvis --voice-test", file=sys.stderr)
        return 2
    if args.neural_preview:
        from jarvis.ui.neural_preview import run_preview
        return run_preview(particles=args.neural_particles, pixel_ratio=args.neural_pixel_ratio, fps=args.neural_fps,
                           style=args.neural_style)
    if args.status:
        path = root / "data/runtime.json"
        if not path.is_file():
            print("Stato runtime non disponibile: riavvia JARVIS aggiornato.")
            return 1
        print(json.dumps(json.loads(path.read_text(encoding='utf-8')), ensure_ascii=True, indent=2))
        return 0
    if not args.voice_test and not args.voice_compare:
        from run import main as desktop_main
        return desktop_main(dashboard=args.dashboard, microphone=False if args.no_microphone else None)
    from PySide6.QtCore import QLockFile
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QMessageBox
    from jarvis.infrastructure.settings import load_settings
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("JARVIS Voice Test")
    app.setFont(QFont("Segoe UI", 10))
    (root / "data").mkdir(exist_ok=True)
    lock = QLockFile(str(root / ("data/voice-compare.lock" if args.voice_compare else "data/voice-test.lock")))
    if not lock.tryLock(0):
        QMessageBox.information(None, "JARVIS", "La finestra vocale richiesta è già aperta.")
        return 3
    app.setStyleSheet((root / "jarvis/ui/theme.qss").read_text(encoding="utf-8"))
    if args.voice_compare:
        from jarvis.ui.voice_comparison import VoiceComparisonWindow
        if not (root / "data/voice-comparison/manifest.json").is_file():
            QMessageBox.information(None, "JARVIS", "Genera i campioni con .venv\\Scripts\\python.exe scripts/compare_voices.py")
            return 2
        window = VoiceComparisonWindow(root)
    else:
        from jarvis.ui.voice_test import VoiceTestWindow
        window = VoiceTestWindow(root, load_settings(root))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
