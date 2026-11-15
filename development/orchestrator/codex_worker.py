"""Bounded real Codex exec invocations; JSONL receipts are required for success."""

import json
from pathlib import Path
import queue
import threading
import time

from .permissions import clean_environment, codex_executable, override_arguments, worker_overrides


def validate_response(value, schema):
    kind = schema.get("type")
    valid = {"object": lambda: isinstance(value, dict), "array": lambda: isinstance(value, list),
             "string": lambda: isinstance(value, str), "boolean": lambda: type(value) is bool,
             "integer": lambda: type(value) is int}.get(kind, lambda: False)()
    if not valid or ("enum" in schema and value not in schema["enum"]):
        raise ValueError("Agent response has an invalid type or enum")
    if kind == "object":
        properties = schema.get("properties", {})
        if any(key not in value for key in schema.get("required", [])) or set(value) - set(properties):
            raise ValueError("Agent output violates its response contract")
        for key, item in value.items():
            validate_response(item, properties[key])
    elif kind == "array":
        if len(value) > 100:
            raise ValueError("Agent response array exceeds its output quota")
        for item in value:
            validate_response(item, schema["items"])
    elif kind == "string" and len(value) > 30000:
        raise ValueError("Agent response text exceeds its output quota")


def execute_codex(job, workspace, folder, role, prompt, schema, *, readonly, checkpoint,
                  readonly_files=(), on_update=lambda data: None, timeout=300):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    schema_file = folder / "schema.json"
    answer_file = folder / "answer.json"
    schema_file.write_text(json.dumps(schema), encoding="utf-8")
    (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
    overrides = worker_overrides(workspace, readonly=readonly, readonly_files=readonly_files)
    command = [str(codex_executable()), "--no-daemon", "exec", "--ignore-user-config", "--ephemeral",
               "--strict-config", *override_arguments(overrides), "--cd", str(workspace), "--json",
               "--color", "never", "--output-schema", str(schema_file), "--output-last-message", str(answer_file), "-"]
    receipt = {"role": role, "status": "starting", "real_thread_started": False,
               "turn_completed": False, "usage": {}, "commands": [], "file_changes": []}
    started = time.monotonic()
    events = queue.Queue(maxsize=1024)
    stdout_log = folder / "events.jsonl"
    with (folder / "stderr.log").open("wb") as error:
        process = job.spawn(command, cwd=workspace, env=clean_environment(keep_auth_transport=True),
                            stderr=error, pid_file=folder / "process.json")
        receipt["supervisor_pid"] = process.pid
        process.send(prompt)
        process.eof()

        def read_events():
            total = 0
            with stdout_log.open("wb") as output:
                for raw in process.stdout:
                    total += len(raw)
                    if total > 8_000_000:
                        events.put({"type": "output_limit_exceeded"})
                        return
                    output.write(raw)
                    output.flush()
                    try:
                        event = json.loads(raw)
                    except ValueError:
                        event = {"type": "invalid_jsonl", "text": raw.decode("utf-8", errors="replace")[:300]}
                    events.put(event)

        reader = threading.Thread(target=read_events, daemon=True)
        reader.start()
        on_update(dict(receipt))
        while reader.is_alive() or not events.empty() or process.poll() is None:
            checkpoint()
            if time.monotonic() - started > timeout:
                raise TimeoutError(f"Codex {role} exceeded {timeout} seconds")
            if (folder / "stderr.log").stat().st_size > 2_000_000:
                raise RuntimeError("Codex stderr log quota exceeded")
            pid_file = folder / "process.json"
            if "target_pid" not in receipt and pid_file.is_file():
                receipt.update(json.loads(pid_file.read_text(encoding="utf-8")))
            try:
                event = events.get(timeout=0.2)
            except queue.Empty:
                continue
            kind = event.get("type")
            if kind in {"output_limit_exceeded", "invalid_jsonl"}:
                raise RuntimeError("Codex emitted invalid or excessive output")
            if kind == "thread.started":
                receipt.update(real_thread_started=True, thread_id=event.get("thread_id"), status="running")
            elif kind == "turn.completed":
                receipt.update(turn_completed=True, usage=event.get("usage", {}))
            elif kind == "turn.failed":
                receipt.setdefault("errors", []).append(event)
            elif kind == "error":
                # Codex reports reconnect attempts as error events even when the
                # same turn later completes successfully. Keep the evidence;
                # exit status and terminal turn outcome determine success.
                receipt.setdefault("transport_events", []).append(event)
            elif kind == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "command_execution":
                    receipt["commands"].append({"command": item.get("command"), "exit_code": item.get("exit_code")})
                elif item.get("type") == "file_change":
                    receipt["file_changes"].append(item.get("changes", []))
            on_update(dict(receipt))
        receipt.update(exit_code=process.wait(timeout=5), seconds=round(time.monotonic() - started, 3))
        process.stdout.close()
    if (receipt["exit_code"] != 0 or not receipt["real_thread_started"] or not receipt["turn_completed"]
            or not answer_file.is_file() or receipt.get("errors")):
        receipt["status"] = "failed"
        (folder / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        on_update(dict(receipt))
        raise RuntimeError(f"Codex {role} did not complete; inspect {folder / 'stderr.log'}")
    answer = json.loads(answer_file.read_text(encoding="utf-8"))
    validate_response(answer, schema)
    receipt["status"] = "completed"
    (folder / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    on_update(dict(receipt))
    return answer, receipt
