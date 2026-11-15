"""Windows PowerShell adapter with cancellation, bounded output and no console."""

import base64
import os
from pathlib import Path
import subprocess
import tempfile

from jarvis.core.models import UserError


def powershell(command, context, *, payload=None, cwd=None):
    if os.name != "nt":
        raise UserError("Questo strumento richiede Windows.")
    executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    environment = os.environ.copy()
    if payload is not None:
        import json
        environment["JARVIS_TOOL_INPUT"] = json.dumps(payload, ensure_ascii=True)
    prefix = ("[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
              "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue';\n")
    wrapped = prefix + "try {\n" + command + "\n} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }\n"
    encoded = base64.b64encode(wrapped.encode("utf-16-le")).decode("ascii")
    if len(encoded) > 32200:
        raise UserError("Comando troppo lungo per Windows. Dividi l'operazione in comandi piu' brevi.")
    context.checkpoint()
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(
            [str(executable), "-NoLogo", "-NoProfile", "-NonInteractive", "-OutputFormat", "Text", "-EncodedCommand", encoded],
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            env=environment, cwd=cwd, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            while process.poll() is None:
                context.checkpoint()
                if os.fstat(output.fileno()).st_size > 1_000_000:
                    raise UserError("Output del comando oltre il limite di 1 MB. Riduci la richiesta.")
                try:
                    process.wait(timeout=0.05)
                except subprocess.TimeoutExpired:
                    pass
            context.checkpoint()
            output.seek(0)
            raw = output.read(1_000_001)
            if len(raw) > 1_000_000:
                raise UserError("Output del comando oltre il limite di 1 MB. Riduci la richiesta.")
            return process.returncode, raw.decode("utf-8-sig", errors="replace").strip()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
