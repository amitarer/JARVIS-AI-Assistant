"""Launch from the project virtual environment: .venv\\Scripts\\python.exe run.py."""

import sys
from pathlib import Path


def main(*, dashboard: bool | None = None, microphone: bool | None = None) -> int:
    if sys.version_info[:2] != (3, 12):
        print("JARVIS richiede Python 3.12. Usa .venv\\Scripts\\python.exe run.py", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parent
    if Path(sys.prefix).resolve() != (root / ".venv").resolve():
        print("Usa esclusivamente .venv\\Scripts\\python.exe run.py", file=sys.stderr)
        return 2
    try:
        from PySide6.QtCore import QLockFile, QTimer
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        print("Dipendenze mancanti. Consulta README.md per l'installazione nella .venv.", file=sys.stderr)
        return 2
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("JARVIS")
    from jarvis import __version__
    app.setApplicationVersion(__version__)
    app.setFont(QFont("Segoe UI", 10))
    try:
        from jarvis.bootstrap import build_controller, ensure_local_data
        from jarvis.infrastructure.settings import load_settings
        from jarvis.ui.main_window import MainWindow
        from jarvis.ui.presenter import Presenter
        from jarvis.ui.background import BackgroundDesktop

        ensure_local_data(load_settings(root))
        instance_lock = QLockFile(str(root / "data/jarvis.lock"))
        if not instance_lock.tryLock(0):
            QMessageBox.information(None, "JARVIS", "JARVIS è già aperto oppure la cartella dati non è accessibile.")
            return 3
        controller = build_controller(root)
        app.setStyleSheet((root / "jarvis/ui/theme.qss").read_text(encoding="utf-8"))
        window = MainWindow()
        presenter = Presenter(window, controller)
        desktop = BackgroundDesktop(presenter)
        show_dashboard = not controller.settings.desktop.start_hidden if dashboard is None else dashboard
        listen = controller.settings.desktop.auto_listen if microphone is None else microphone
        QTimer.singleShot(0, lambda: desktop.start(dashboard=show_dashboard, auto_listen=listen))
        return app.exec()
    except Exception as exc:
        QMessageBox.critical(None, "JARVIS · Avvio non riuscito",
                             f"Impossibile avviare JARVIS ({type(exc).__name__}).\n"
                             "Verifica configurazione, dipendenze e accesso alla cartella data.\n"
                             "Nessuna impostazione di sistema è stata modificata.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
