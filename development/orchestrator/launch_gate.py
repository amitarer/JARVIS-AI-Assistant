"""Trusted launch gate: no target starts until the parent assigns this job.

Two JSON lines: launch specification, then stdin chunks. The parent writes the
specification only after AssignProcessToJobObject succeeds. No shell strings.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import threading


def main():
    specification = json.loads(sys.stdin.buffer.readline())
    child = subprocess.Popen(specification["argv"], cwd=specification["cwd"], env=specification["env"],
                             stdin=subprocess.PIPE, stdout=None, stderr=None,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), shell=False)
    if specification.get("pid_file"):
        Path(specification["pid_file"]).write_text(json.dumps({"supervisor_pid": os.getpid(),
            "target_pid": child.pid, "executable": specification["argv"][0]}), encoding="utf-8")

    def forward():
        try:
            for line in sys.stdin.buffer:
                message = json.loads(line)
                if message.get("eof"):
                    break
                child.stdin.write(message["text"].encode("utf-8"))
                child.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                child.stdin.close()
            except OSError:
                pass

    threading.Thread(target=forward, daemon=True).start()
    status = child.wait()
    # An interactive target may exit while the forwarding daemon is blocked on
    # stdin. There are no gate-owned buffered outputs to flush; avoid finalizing
    # Python with that reader lock held. OS cleanup closes the remaining pipe.
    os._exit(status if 0 <= status <= 255 else 1)


if __name__ == "__main__":
    raise SystemExit(main())
