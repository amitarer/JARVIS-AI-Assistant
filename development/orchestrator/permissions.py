"""Least-privilege MXC profiles generated locally, with no global config edits."""

import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".devtools"
STATE = ROOT / ".development-state"


def codex_executable():
    found = shutil.which("codex")
    if found and found.lower().endswith(".exe"):
        return Path(found).resolve()
    extensions = Path(os.environ["USERPROFILE"]) / ".vscode/extensions"
    choices = list(extensions.glob("openai.chatgpt-*/bin/windows-x86_64/codex.exe"))
    choices += list(extensions.glob("openai.chatgpt-*/bin/windows-x64/codex.exe"))
    if not choices:
        raise RuntimeError("Codex executable not found; no automatic installation or API fallback")
    return max(choices, key=lambda path: path.stat().st_mtime)


def clean_environment(*, temporary=None, keep_auth_transport=False):
    # Explicit allowlist: never pass model-provider API keys, npm tokens or
    # app credentials to workers. Codex itself reuses its existing login.
    allowed = {"SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "PROCESSOR_ARCHITECTURE",
               "NUMBER_OF_PROCESSORS", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA",
               "APPDATA", "TEMP", "TMP", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA"}
    if keep_auth_transport:
        allowed |= {"CODEX_HOME", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    system = Path(os.environ.get("SystemRoot", "C:/Windows"))
    env["PATH"] = os.pathsep.join((str(TOOLS / "git/cmd"), str(TOOLS / "node"),
                                   str(system / "System32"), str(system),
                                   str(system / "System32/WindowsPowerShell/v1.0")))
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", DO_NOT_TRACK="1")
    if temporary:
        Path(temporary).mkdir(parents=True, exist_ok=True)
        env["TEMP"] = env["TMP"] = str(temporary)
    return env


def profile(workspace, *, readonly=False, extra_read=(), readonly_files=()):
    workspace = Path(workspace).resolve()
    # The custom profile already denies unlisted paths. Explicitly denying
    # whole ancestor directories breaks CreateProcess for otherwise permitted
    # binaries on MXC; keep narrow sensitive-path denies instead.
    home = Path(os.environ["USERPROFILE"]).resolve()
    filesystem = {":minimal": "read", str(home / ".codex"): "deny", str(home / ".ssh"): "deny",
                  str(home / "Documents"): "deny", str(home / "Downloads"): "deny",
                  str(ROOT / "data"): "deny", str(ROOT / ".env"): "deny",
                  str(Path(sys.base_prefix).resolve()): "read",
                  str(codex_executable().parent): "read",
                  str(workspace): "read" if readonly else "write"}
    for path in extra_read:
        filesystem[str(Path(path).resolve())] = "read"
    for relative in readonly_files:
        filesystem[str(workspace / relative)] = "read"
    filesystem[str(workspace / ".git")] = "deny"
    filesystem[str(workspace / ".env")] = "deny"
    filesystem[str(workspace / ".codex")] = "deny"
    filesystem[str(workspace / ".agents")] = "deny"
    return {"description": "JARVIS isolated development task: no private files or command networking",
            "filesystem": filesystem, "network": {"enabled": False}}


def toml_value(value):
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(key) + "=" + toml_value(item) for key, item in value.items()) + "}"
    return json.dumps(value, ensure_ascii=True)


def worker_overrides(workspace, *, readonly=False, readonly_files=()):
    safe_env = clean_environment(temporary=Path(workspace) / ".tmp")
    # Model command environments do not receive USERPROFILE/AppData or proxies.
    shell_env = {key: value for key, value in safe_env.items() if key.upper() in
                 {"SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "PATH", "TEMP", "TMP",
                  "PYTHONUTF8", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE"}}
    return {
        "default_permissions": "jarvis-worker", "windows.sandbox": "mxc", "approval_policy": "never",
        "permissions.jarvis-worker": profile(workspace, readonly=readonly, readonly_files=readonly_files),
        "features.apps": False, "features.plugins": False, "features.remote_plugin": False,
        "features.multi_agent": False, "features.multi_agent_v2": False,
        "features.shell_snapshot": False, "features.skip_host_skill_discovery": True,
        "features.skill_search": False, "web_search": "disabled",
        "shell_environment_policy.inherit": "none", "shell_environment_policy.set": shell_env,
    }


def override_arguments(values):
    return [argument for key, value in values.items() for argument in ("-c", key + "=" + toml_value(value))]


def sandbox_command(argv, workspace, *, name="probe", readonly=False, extra_read=(), readonly_files=()):
    home = STATE / "sandbox-homes" / name
    home.mkdir(parents=True, exist_ok=True)
    contents = (f'default_permissions = "jarvis-{name}"\n[windows]\nsandbox = "mxc"\n'
                f'[permissions.jarvis-{name}]\n')
    spec = profile(workspace, readonly=readonly, extra_read=extra_read, readonly_files=readonly_files)
    contents += 'description = "Isolated local JARVIS development tooling"\n'
    contents += f'[permissions.jarvis-{name}.filesystem]\n'
    contents += "\n".join(json.dumps(key) + " = " + json.dumps(value) for key, value in spec["filesystem"].items())
    contents += f'\n[permissions.jarvis-{name}.network]\nenabled = false\n'
    (home / "config.toml").write_text(contents, encoding="utf-8")
    env = clean_environment(temporary=Path(workspace) / ".tmp")
    env["CODEX_HOME"] = str(home)
    command = [str(codex_executable()), "-c", 'windows.sandbox="mxc"', "sandbox", "--permission-profile",
               f"jarvis-{name}", "--cd", str(workspace), "--", *map(str, argv)]
    return command, env
