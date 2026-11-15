"""Configuration is read only from this project, never parent directories."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values


@dataclass(frozen=True)
class Application:
    label: str
    executable: Path
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class VoiceSettings:
    sensitivity: float = 0.55
    conversation_seconds: int = 30
    silence_seconds: float = 1.2
    max_utterance_seconds: int = 25
    microphone_id: str = ""
    voice_name: str = "Microsoft Cosimo"
    model_path: str = "assets/wakeword/Jarvis_20260313_215039.onnx"
    continuous_conversation: bool = True


@dataclass(frozen=True)
class DesktopSettings:
    start_hidden: bool = False
    auto_listen: bool = True


@dataclass(frozen=True)
class OllamaSettings:
    enabled: bool = False
    url: str = "http://127.0.0.1:11434"
    model: str = "qwen3.5:9b"
    timeout_seconds: int = 180
    max_tool_rounds: int = 5


@dataclass(frozen=True)
class Settings:
    root: Path
    log_level: str
    reduced_motion: bool
    task_timeout_seconds: int
    approval_timeout_seconds: int
    applications: dict[str, Application]
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    ollama: OllamaSettings = field(default_factory=OllamaSettings)
    desktop: DesktopSettings = field(default_factory=DesktopSettings)

    @property
    def data_dir(self) -> Path:
        return self.root / "data"


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ValueError("JARVIS_REDUCED_MOTION deve essere true oppure false.")


def load_settings(root: Path) -> Settings:
    root = root.resolve(strict=True)
    defaults = json.loads((root / "config/defaults.json").read_text(encoding="utf-8"))
    local = dotenv_values(root / ".env", interpolate=False)
    level = os.environ.get("JARVIS_LOG_LEVEL", local.get("JARVIS_LOG_LEVEL") or defaults["log_level"])
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ValueError("Livello di log non valido.")
    motion = os.environ.get(
        "JARVIS_REDUCED_MOTION", local.get("JARVIS_REDUCED_MOTION") or defaults["reduced_motion"]
    )
    applications: dict[str, Application] = {}
    raw = json.loads((root / "config/applications.json").read_text(encoding="utf-8"))
    blocked = {"cmd.exe", "powershell.exe", "pwsh.exe", "python.exe", "pythonw.exe",
               "wscript.exe", "cscript.exe", "mshta.exe", "rundll32.exe", "regsvr32.exe"}
    for identifier, entry in raw.items():
        executable = Path(entry["executable"])
        if not identifier.isidentifier() or not executable.is_absolute():
            raise ValueError("Applicazione configurata con identificatore o percorso non valido.")
        if executable.suffix.casefold() != ".exe" or executable.name.casefold() in blocked:
            raise ValueError("Eseguibile non ammesso nella lista applicazioni.")
        if not isinstance(entry["label"], str) or not entry["label"].strip():
            raise ValueError("Etichetta applicazione non valida.")
        aliases = entry.get("aliases", [])
        if (not isinstance(aliases, list) or len(aliases) > 30
                or any(not isinstance(alias, str) or not alias.strip() or len(alias) > 100
                       or any(ord(char) < 32 for char in alias) for alias in aliases)):
            raise ValueError("Nomi alternativi dell'applicazione non validi.")
        applications[identifier] = Application(entry["label"], executable, tuple(alias.strip() for alias in aliases))
    timeout = defaults["task_timeout_seconds"]
    approval = defaults["approval_timeout_seconds"]
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise ValueError("Timeout attività non valido.")
    if type(approval) is not int or not 1 <= approval <= 300:
        raise ValueError("Timeout conferma non valido.")
    def value(name: str, default: str = "") -> str:
        return os.environ.get(name, local.get(name) or default)

    raw_voice = dict(defaults.get("voice", {}))
    raw_voice["model_path"] = value("JARVIS_WAKE_MODEL", raw_voice.get("model_path", VoiceSettings().model_path))
    voice = validate_voice(raw_voice)
    raw_ollama = defaults.get("ollama", {})
    url = value("JARVIS_OLLAMA_URL", raw_ollama.get("url", "http://127.0.0.1:11434"))
    validate_local_url(url)
    ollama = OllamaSettings(parse_bool(raw_ollama.get("enabled", False)), url,
                            value("JARVIS_OLLAMA_MODEL", raw_ollama.get("model", "qwen3.5:9b")),
                            int(raw_ollama.get("timeout_seconds", 180)),
                            int(raw_ollama.get("max_tool_rounds", 5)))
    if not 10 <= ollama.timeout_seconds <= 600 or not 1 <= ollama.max_tool_rounds <= 12:
        raise ValueError("Limiti Ollama non validi.")
    desktop = DesktopSettings(**defaults.get("desktop", {}))
    if type(desktop.start_hidden) is not bool or type(desktop.auto_listen) is not bool:
        raise ValueError("Configurazione desktop non valida.")
    return Settings(root, level, parse_bool(motion), timeout, approval, applications, voice, ollama, desktop)


def validate_local_url(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment):
        raise ValueError("Ollama deve usare un endpoint HTTP di loopback, senza credenziali o percorsi.")
    if parsed.port is None:
        raise ValueError("Specificare la porta locale di Ollama.")


def validate_voice(values: dict) -> VoiceSettings:
    allowed = {"sensitivity", "conversation_seconds", "silence_seconds", "max_utterance_seconds",
               "microphone_id", "voice_name", "model_path", "continuous_conversation"}
    if not isinstance(values, dict) or set(values) - allowed:
        raise ValueError("Preferenze vocali non valide.")
    voice = VoiceSettings(**values)
    if (type(voice.sensitivity) not in {int, float} or not 0.1 <= voice.sensitivity <= 0.95
            or type(voice.conversation_seconds) is not int or not 5 <= voice.conversation_seconds <= 120
            or type(voice.silence_seconds) not in {int, float} or not 0.5 <= voice.silence_seconds <= 3
            or type(voice.max_utterance_seconds) is not int or not 5 <= voice.max_utterance_seconds <= 60
            or not isinstance(voice.microphone_id, str) or len(voice.microphone_id) > 2048
            or not isinstance(voice.voice_name, str) or len(voice.voice_name) > 200
            or not isinstance(voice.model_path, str) or not voice.model_path.endswith(".onnx")
            or type(voice.continuous_conversation) is not bool):
        raise ValueError("Sensibilità, durata o dispositivo vocale non validi.")
    return voice
