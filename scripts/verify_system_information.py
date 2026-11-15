"""Phase 1 native checks and optional real Qwen checks, with isolated SQLite."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis.bootstrap import build_tool_registry
from jarvis.core.controller import Controller
from jarvis.core.models import Cancelled, UserError, ToolCall
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import load_settings
from jarvis.infrastructure.system_information import SystemInformation
from jarvis.infrastructure.windows import powershell
from jarvis.memory.database import Database
from jarvis.memory.repository import Repository


REFERENCE = r"""
$system = Get-CimInstance Win32_OperatingSystem -OperationTimeoutSec 10
$drive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID = '$($env:SystemDrive)'" -OperationTimeoutSec 10
$now = Get-Date
@{ utc = $now.ToUniversalTime().ToString('o'); local_iso = $now.ToString('o'); date = $now.ToString('yyyy-MM-dd');
   timezone_id = (Get-TimeZone).Id; os_name = $system.Caption; os_version = $system.Version;
   cpus = @(Get-CimInstance Win32_Processor -OperationTimeoutSec 10 | ForEach-Object { $_.Name.Trim() });
   gpus = @(Get-CimInstance Win32_VideoController -OperationTimeoutSec 10 | ForEach-Object { $_.Name });
   ram_total_bytes = [long]$system.TotalVisibleMemorySize * 1024;
   ram_available_bytes = [long]$system.FreePhysicalMemory * 1024;
   system_drive = $env:SystemDrive + '\'; disk_total_bytes = [long]$drive.Size; disk_free_bytes = [long]$drive.FreeSpace } |
    ConvertTo-Json -Depth 5 -Compress
"""


def main(with_ollama=False):
    folder = ROOT / "data/verification"
    folder.mkdir(parents=True, exist_ok=True)
    report = {"phase": 1, "checks": {}, "observations": {}, "llm_requests": [], "passed": False}
    context = TaskContext("system-native-checks", threading.Event(), 60)
    service = SystemInformation()
    checks = report["checks"]
    try:
        before = datetime.now(timezone.utc)
        clock = service.get_current_datetime(context)
        after = datetime.now(timezone.utc)
        observed = datetime.fromisoformat(clock["observed_at_utc"])
        checks["native_clock_within_one_second"] = before.timestamp() - 1 <= observed.timestamp() <= after.timestamp() + 1
        code, output = powershell(REFERENCE, context)
        if code:
            raise RuntimeError("Impossibile interrogare i riferimenti Windows in sola lettura.")
        reference = json.loads(output)
        checks["local_date_matches_windows"] = clock["date"] == reference["date"]
        checks["timezone_matches_windows"] = clock["timezone"]["windows_id"] == reference["timezone_id"]
        report["observations"]["datetime"] = clock

        system = service.get_system_information(context)
        checks["windows_version_matches_cim"] = system["os_name"] == reference["os_name"] and system["os_version"] == reference["os_version"]
        checks["uptime_and_computer_name_available"] = system["uptime_seconds"] > 0 and bool(system["computer_name"])
        hardware = service.get_hardware_information(context)
        checks["cpu_matches_windows"] = sorted(cpu["name"] for cpu in hardware["processors"]) == sorted(reference["cpus"])
        checks["gpu_matches_windows"] = sorted(gpu["name"] for gpu in hardware["graphics_adapters"]) == sorted(reference["gpus"])
        checks["cpu_usage_measured"] = hardware["cpu_usage"]["percent"] is not None and 0 <= hardware["cpu_usage"]["percent"] <= 100
        memory = hardware["memory"]
        checks["ram_total_matches_windows"] = abs(memory["total_bytes"] - reference["ram_total_bytes"]) < 1024**2
        checks["ram_available_matches_windows_sample"] = (0 <= memory["available_bytes"] <= memory["total_bytes"]
                                                           and abs(memory["available_bytes"] - reference["ram_available_bytes"]) < 1024**3)
        disk = next(item for item in hardware["disks"] if item["path"].casefold() == reference["system_drive"].casefold())
        checks["disk_matches_windows_sample"] = disk["total_bytes"] == reference["disk_total_bytes"] and abs(disk["free_bytes"] - reference["disk_free_bytes"]) < 1024**3
        report["observations"]["system"] = system
        report["observations"]["hardware"] = hardware

        processes = service.get_process_information(context, query="python", limit=50)
        checks["own_process_visible"] = any(row["process_id"] == os.getpid() for row in processes["processes"])
        checks["process_resources_available"] = all(row["memory_working_set_bytes"] >= 0 and row["cpu_time_seconds"] >= 0
                                                    and row["cpu_percent"] is not None and 0 <= row["cpu_percent"] <= 100
                                                    for row in processes["processes"])
        checks["processes_have_no_command_lines_or_credentials"] = all(not {"command_line", "environment", "token", "password"} & row.keys()
                                                                       for row in processes["processes"])
        report["observations"]["process_sample_count"] = processes["returned"]
        applications = service.get_open_applications(context)
        checks["open_windows_and_foreground_read"] = isinstance(applications["windows"], list) and isinstance(applications["foreground_window_id"], int)
        report["observations"]["open_window_count"] = len(applications["windows"])

        settings = load_settings(ROOT)
        database = Database(folder / ("system-info-" + secrets.token_hex(4) + ".sqlite3"))
        database.initialize()
        repository = Repository(database)
        registry = build_tool_registry(settings, repository)
        report["test_database"] = str(database.path)
        try:
            registry.execute(ToolCall("get_current_datetime", '{"unexpected":"value"}'), context, lambda *_: None)
            checks["invalid_parameters_denied"] = False
        except UserError:
            checks["invalid_parameters_denied"] = True
        try:
            registry.execute(ToolCall("run_powershell", '{"command":"Write-Output test"}'), context, lambda *_: None)
            checks["generated_shell_tool_denied"] = False
        except UserError:
            checks["generated_shell_tool_denied"] = True

        cancellation = threading.Event()
        cancelled_context = TaskContext("real-system-cancellation", cancellation, 10)
        timer = threading.Timer(0.05, cancellation.set)
        started = time.monotonic()
        timer.start()
        try:
            service.get_process_information(cancelled_context, limit=5)
            checks["native_stop_interrupts_collector"] = False
        except Cancelled:
            elapsed = time.monotonic() - started
            checks["native_stop_interrupts_collector"] = elapsed < 2
            report["observations"]["stop_seconds"] = round(elapsed, 3)
        finally:
            timer.cancel()

        controller = Controller(settings, repository, registry)
        repository.create_task("native-clock-audit", "system_info", "Lettura orario di verifica Fase 1")
        controller.execute_tool(ToolCall("get_current_datetime", "{}"),
                                TaskContext("native-clock-audit", threading.Event(), 5), lambda *_: None,
                                lambda *_: (_ for _ in ()).throw(AssertionError("Lettura senza conferma")))
        repository.set_task_status("native-clock-audit", "succeeded")
        audit = repository.operations()[0]
        checks["live_observation_saved_in_sqlite"] = audit["status"] == "succeeded" and json.loads(audit["evidence_json"])["read_only"]

        if with_ollama:
            def before_tool(name, task):
                if not name.startswith("get_") and name != "read_operations":
                    raise UserError("La verifica Fase 1 consente soltanto letture di sistema.")

            prompts = [("Che ore sono?", "get_current_datetime"),
                       ("Che giorno e' oggi? Dimmi data e giorno della settimana.", "get_current_datetime"),
                       ("Quali CPU e GPU ha questo computer?", "get_hardware_information"),
                       ("Quanta RAM e' disponibile adesso?", "get_memory_information"),
                       ("Quanto spazio libero c'e' sul disco C: ?", "get_disk_information")]
            for prompt, expected_tool in prompts:
                events = []
                started = time.monotonic()
                controller.run({"kind": "chat", "text": prompt}, threading.Event(), events.append, lambda *_: None, before_tool)
                task = repository.tasks()[0]
                operations = [row for row in repository.operations(limit=50) if row["task_id"] == task["id"]]
                calls = [row["tool"] for row in operations]
                responses = [event.data for event in events if event.kind == "response"]
                item = {"request": prompt, "answer": responses[-1] if responses else None, "status": task["status"],
                        "tools": calls, "seconds": round(time.monotonic() - started, 2)}
                passed = task["status"] == "succeeded" and expected_tool in calls
                if expected_tool == "get_current_datetime" and passed:
                    data = json.loads(next(row["result_text"] for row in operations if row["tool"] == expected_tool))
                    if prompt.startswith("Che ore"):
                        passed = data["time_it"] in (item["answer"] or "")
                    else:
                        answer = (item["answer"] or "").casefold()
                        passed = data["weekday_it"] in answer and str(datetime.fromisoformat(data["date"]).year) in answer
                checks["llm_" + str(len(report["llm_requests"]) + 1) + "_" + expected_tool] = passed
                report["llm_requests"].append(item)
                print(json.dumps(item, ensure_ascii=True), flush=True)

        report["passed"] = all(checks.values())
    finally:
        report["written_at_utc"] = datetime.now(timezone.utc).isoformat()
        path = folder / "system-information.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "checks": checks, "report": str(path)}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-ollama", action="store_true", help="Verifica anche cinque richieste al modello locale reale")
    args = parser.parse_args()
    raise SystemExit(main(args.with_ollama))
