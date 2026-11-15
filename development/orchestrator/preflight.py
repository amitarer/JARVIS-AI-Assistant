"""Synthetic canaries and owned-child STOP: refuse execution if isolation fails."""

import json
from pathlib import Path
import socket
import subprocess
import sys
import time

from .permissions import ROOT, STATE, TOOLS, clean_environment, sandbox_command
from .windows_job import WindowsJob


def wait_process(process, timeout=30):
    process.eof()
    deadline = time.monotonic() + timeout
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if process.poll() is None:
        raise TimeoutError("Preflight child timeout")
    output = process.stdout.read().decode("utf-8", errors="replace")
    error = process.stderr.read().decode("utf-8", errors="replace")
    process.stdout.close()
    process.stderr.close()
    return output, error


def verify_sandbox(job):
    workspace = STATE / "probe-workspace"
    private = STATE / "probe-private"
    workspace.mkdir(parents=True, exist_ok=True)
    private.mkdir(parents=True, exist_ok=True)
    (private / "canary.txt").write_text("SYNTHETIC-NOT-A-CREDENTIAL", encoding="utf-8")
    (workspace / "readable.txt").write_text("READ_ALLOWED", encoding="utf-8")
    (workspace / "readonly.txt").write_text("DO_NOT_CHANGE", encoding="utf-8")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        script = '''import json,socket,subprocess,sys
from pathlib import Path
result={}
result['can_read_assigned_file']=Path('readable.txt').read_text()=='READ_ALLOWED'
Path('allowed-output.txt').write_text('WRITE_ALLOWED')
result['can_write_assigned_file']=True
child=subprocess.run([sys.executable,'-I','-S','-c','print(42)'],capture_output=True,text=True,timeout=4)
result['permitted_child_process_works']=child.returncode==0 and child.stdout.strip()=='42'
for key,path,mode in [('private_read_denied',PRIVATE/'canary.txt','read'),('outside_write_denied',PRIVATE/'forbidden-write.txt','write'),('readonly_write_denied',Path('readonly.txt'),'write')]:
    try:
        path.read_text() if mode=='read' else path.write_text('SHOULD_NOT_BE_WRITTEN')
        result[key]=False
    except (OSError,PermissionError): result[key]=True
try:
    s=socket.create_connection(('127.0.0.1',PORT),timeout=1);s.close();result['network_denied']=False
except OSError: result['network_denied']=True
print(json.dumps(result))
'''
        script = "from pathlib import Path\nPRIVATE=Path(" + repr(str(private)) + ")\nPORT=" + str(port) + "\n" + script
        interpreter = Path(sys.base_prefix) / "python.exe"
        command, env = sandbox_command([interpreter, "-I", "-S", "-B", "-c", script], workspace,
                                       readonly_files=("readonly.txt",))
        process = job.spawn(command, cwd=workspace, env=env)
        output, error = wait_process(process)
    report = {"exit_code": process.poll(), "stderr": error[-3000:], "stdout": output[-3000:]}
    try:
        report["checks"] = json.loads(output.strip().splitlines()[-1])
    except (ValueError, IndexError):
        report["checks"] = {}
    report["checks"]["readonly_content_preserved"] = (workspace / "readonly.txt").read_text() == "DO_NOT_CHANGE"
    report["checks"]["no_outside_file_created"] = not (private / "forbidden-write.txt").exists()
    report["passed"] = report["exit_code"] == 0 and len(report["checks"]) == 9 and all(report["checks"].values())
    return report


def verify_stop():
    # Dedicated job; the unrelated observer must survive termination.
    env = clean_environment()
    interpreter = Path(sys.base_prefix) / "python.exe"
    observer = subprocess.Popen([str(interpreter), "-I", "-S", "-c", "import time;time.sleep(30)"],
                                env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        with WindowsJob(memory_mib=512, cpu_percent=10) as job:
            owned = job.spawn([interpreter, "-I", "-S", "-c", "import time;time.sleep(30)"], cwd=ROOT, env=env)
            owned.eof()
            time.sleep(0.4)
            before = job.sample()
            started = time.monotonic()
            job.terminate()
            owned.wait(timeout=5)
            owned.stdout.close()
            owned.stderr.close()
            report = {"owned_process_exited": owned.poll() is not None,
                      "unrelated_observer_survived": observer.poll() is None,
                      "stop_seconds": round(time.monotonic() - started, 3), "job_limits": before}
            report["passed"] = report["owned_process_exited"] and report["unrelated_observer_survived"] and before["cpu_hard_cap"]
            return report
    finally:
        observer.terminate()
        observer.wait(timeout=5)


def main():
    STATE.mkdir(exist_ok=True)
    with WindowsJob() as job:
        report = {"sandbox": verify_sandbox(job), "resources": job.sample(), "stop": verify_stop()}
    report["passed"] = report["sandbox"]["passed"] and report["stop"]["passed"]
    (STATE / "isolation-preflight.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
