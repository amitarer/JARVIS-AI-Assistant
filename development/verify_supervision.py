"""Actual Qt STOP button -> controller checkpoint -> owned Job Object teardown.

The running fixture is a sleeping child, not a simulated AI agent. No model calls.
An unrelated observer must survive. The real cycle status is left untouched.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from development.orchestrator.permissions import STATE, clean_environment
from development.orchestrator.runner import Cancelled, DevelopmentRunner, atomic_json
from development.orchestrator.windows_job import WindowsJob


def probe(folder):
    import development.orchestrator.runner as module
    module.STATE = folder
    runner = object.__new__(DevelopmentRunner)
    runner.started = time.monotonic()
    runner.last_sample = 0
    runner.config = {"limits": {"max_cycle_seconds": 20}}
    runner.folder = folder
    runner.state = {"status": "running", "stage": "STOP_PROBE", "runner_pid": os.getpid(),
                    "task_id": "STOP-FIXTURE", "task_title": "Processo di prova; nessun agente AI", "agents": [], "tests": []}
    with WindowsJob(memory_mib=512, cpu_percent=10) as job:
        runner.job = job
        child = job.spawn([Path(sys.base_prefix) / "python.exe", "-I", "-S", "-c", "import time;time.sleep(30)"],
                          cwd=ROOT, env=clean_environment())
        child.eof()
        runner.publish()
        try:
            while True:
                runner.checkpoint()
                time.sleep(0.05)
        except Cancelled:
            job.terminate()
            child.wait(timeout=3)
            child.stdout.close()
            child.stderr.close()
            runner.state.update(status="cancelled", owned_child_stopped=child.poll() is not None)
            runner.publish()
    return 0


def main():
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from development.monitor import DevelopmentMonitor

    folder = STATE / ("supervision-probe-" + str(os.getpid()))
    folder.mkdir(parents=True, exist_ok=True)
    executable = Path(sys.base_prefix) / "python.exe"
    observer = subprocess.Popen([str(executable), "-I", "-S", "-c", "import time;time.sleep(30)"],
                                creationflags=subprocess.CREATE_NO_WINDOW)
    process = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--probe", str(folder)],
                               cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = DevelopmentMonitor(state_directory=folder)
    window.show()
    started = time.monotonic()
    clicked = None
    report = {"model_executors_started": 0}

    def tick():
        nonlocal clicked
        path = folder / "status.json"
        state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if clicked is None and state.get("status") == "running":
            window.refresh()
            window.grab().save(str(folder / "supervision-stop.png"))
            QTest.mouseClick(window.stop, Qt.MouseButton.LeftButton)
            clicked = time.monotonic()
        elif clicked is not None and state.get("status") == "cancelled":
            report.update(button_created_stop_flag=(folder / "STOP").exists(),
                          owned_child_stopped=state.get("owned_child_stopped"),
                          unrelated_observer_survived=observer.poll() is None,
                          stop_seconds=round(time.monotonic() - clicked, 3))
            report["passed"] = all(report.get(key) for key in ("button_created_stop_flag", "owned_child_stopped", "unrelated_observer_survived")) and report["stop_seconds"] < 3
            timer.stop()
            window.close()
            app.quit()
        elif time.monotonic() - started > 12:
            report.update(passed=False, error="Supervision fixture timed out")
            timer.stop()
            window.close()
            app.quit()

    timer = QTimer()
    timer.setInterval(100)
    timer.timeout.connect(tick)
    timer.start()
    try:
        app.exec()
    finally:
        if process.poll() is None:
            (folder / "STOP").write_text("Fixture cleanup STOP", encoding="utf-8")
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=3)
        observer.terminate()
        observer.wait(timeout=3)
    (STATE / "supervision-verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--probe":
        raise SystemExit(probe(Path(sys.argv[2])))
    raise SystemExit(main())
