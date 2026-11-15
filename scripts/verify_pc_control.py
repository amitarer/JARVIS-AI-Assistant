"""Native PC control smoke test. Only operates on its own disposable test window."""

import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fixture(state):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QVBoxLayout, QWidget

    app = QApplication([])
    window = QWidget()
    window.setWindowTitle("JARVIS - verifica controllo PC")
    window.resize(450, 160)
    layout = QVBoxLayout(window)
    field = QLineEdit()
    field.setAccessibleName("Campo di prova JARVIS")
    button = QPushButton("Pulsante di prova JARVIS")
    layout.addWidget(field)
    layout.addWidget(button)
    clicks = [0]
    button.clicked.connect(lambda: clicks.__setitem__(0, clicks[0] + 1))
    window.show()

    def save():
        temporary = state.with_suffix(".tmp")
        temporary.write_text(json.dumps({"window_id": int(window.winId()), "text": field.text(), "clicks": clicks[0]}), encoding="utf-8")
        temporary.replace(state)

    timer = QTimer()
    timer.timeout.connect(save)
    timer.start(100)
    QTimer.singleShot(60000, app.quit)
    save()
    return app.exec()


def main():
    from jarvis.core.models import ToolCall
    from jarvis.core.tasks import TaskContext
    from jarvis.security.approvals import ApprovalStore
    from jarvis.security.policy import SecurityPolicy
    from jarvis.tools.desktop import DesktopSession, DesktopActionTool, InspectDesktopTool
    from jarvis.tools.pc import RunPowerShellTool
    from jarvis.tools.registry import ToolRegistry

    folder = ROOT / "data/verification"
    folder.mkdir(parents=True, exist_ok=True)
    state = folder / ("pc-fixture-" + secrets.token_hex(4) + ".json")
    process = subprocess.Popen([str(ROOT / ".venv/Scripts/pythonw.exe"), str(Path(__file__).resolve()), "--fixture", str(state)])
    context = TaskContext("native-pc-test", threading.Event(), 60)
    registry = ToolRegistry(SecurityPolicy(ApprovalStore()))
    session = DesktopSession()
    for tool in (DesktopActionTool(session), InspectDesktopTool(session), RunPowerShellTool(ROOT)):
        registry.register(tool)
    window_id = None
    report = {"passed": False}

    def wait_until(predicate):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            context.checkpoint()
            try:
                if predicate():
                    return
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            time.sleep(0.1)
        raise RuntimeError("La finestra di verifica non ha raggiunto lo stato atteso.")

    def approve(request, task):
        params = json.loads(request.call.arguments_json)
        assert (request.call.name == "desktop_action" and params["window_id"] == window_id
                or request.call.name == "run_powershell" and params["command"] == "Write-Output JARVIS_PC_TEST")
        return registry.policy.approvals.issue(request)

    def execute(name, **arguments):
        return registry.execute(ToolCall(name, json.dumps(arguments)), context, approve)

    try:
        wait_until(state.exists)
        window_id = json.loads(state.read_text())["window_id"]
        result = execute("inspect_desktop", window_id=window_id)
        controls = json.loads(result.message)["controls"]
        field = next(control for control in controls if control["name"] == "Campo di prova JARVIS")
        button = next(control for control in controls if control["name"] == "Pulsante di prova JARVIS")
        execute("desktop_action", action="click", window_id=window_id, control_id=field["control_id"])
        text = "Ciao da JARVIS: prova unicode è ✓"
        execute("desktop_action", action="type_text", window_id=window_id, text=text)
        wait_until(lambda: json.loads(state.read_text())["text"] == text)
        report["unicode_typing_verified"] = True
        execute("desktop_action", action="press_keys", window_id=window_id, keys="CTRL+A")
        execute("desktop_action", action="type_text", window_id=window_id, text="JARVIS verificato")
        wait_until(lambda: json.loads(state.read_text())["text"] == "JARVIS verificato")
        report["keyboard_shortcut_verified"] = True
        execute("desktop_action", action="click", window_id=window_id, control_id=button["control_id"])
        wait_until(lambda: json.loads(state.read_text())["clicks"] == 1)
        report["button_click_verified"] = True
        shell = execute("run_powershell", command="Write-Output JARVIS_PC_TEST")
        assert shell.evidence["command_succeeded"] and "JARVIS_PC_TEST" in shell.message
        report["approved_powershell_verified"] = True
        execute("desktop_action", action="close", window_id=window_id)
        process.wait(timeout=5)
        report["window_closed"] = True
        report["passed"] = True
    finally:
        if process.poll() is None:
            if window_id is not None:
                try:
                    execute("desktop_action", action="close", window_id=window_id)
                    process.wait(timeout=5)
                except Exception:
                    pass
            if process.poll() is None:
                subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        (folder / "pc-control.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        state.unlink(missing_ok=True)
        state.with_suffix(".tmp").unlink(missing_ok=True)
    print(json.dumps(report), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--fixture":
        raise SystemExit(fixture(Path(sys.argv[2])))
    raise SystemExit(main())
