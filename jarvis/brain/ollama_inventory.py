"""Read-only local model facts, using JARVIS's existing HTTP transport.

SPDX-License-Identifier: Apache-2.0
Copyright 2026 Ruben Lütke and Personal Jarvis contributors.

same_model/native_context_length adapt PersonalJarvis 2.7.1's module with
the same name. Changes: stricter boolean/non-finite validation, optional
runtime facts and no httpx, cloud discovery, alias creation or model mutation.
See third_party/PersonalJarvis/{LICENSE,NOTICE,README.md}.
"""

from datetime import datetime, timezone
import math


def same_model(a: str, b: str) -> bool:
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    a, b = a.strip(), b.strip()
    if not a or not b:
        return False
    return a.removesuffix(":latest") == b.removesuffix(":latest")


def positive_integer(value, *, allow_zero=False):
    if type(value) not in {int, float} or (type(value) is float and (not math.isfinite(value) or int(value) != value)):
        return None
    return int(value) if (0 if allow_zero else 1) <= value <= 2**63 - 1 else None


def native_context_length(model_info) -> int | None:
    if not isinstance(model_info, dict):
        return None
    arch = model_info.get("general.architecture")
    candidates = [f"{arch}.context_length"] if isinstance(arch, str) and arch.strip() else []
    candidates += [key for key in model_info if isinstance(key, str) and key.endswith(".context_length")]
    for key in candidates:
        value = positive_integer(model_info.get(key))
        if value is not None:
            return value
    return None


def installed_names(payload):
    rows = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("Formato dell'inventario modelli non valido")
    names = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Voce dell'inventario modelli non valida")
        name = row.get("name") or row.get("model")
        if not isinstance(name, str) or not name.strip() or len(name) > 512:
            raise ValueError("Nome modello non valido")
        if name not in names:
            names.append(name)
    return names


def runtime_facts(payload, configured_model):
    rows = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("Formato dello stato Ollama non valido")
    partial = False
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("name") or row.get("model"), str)
                or not (row.get("name") or row.get("model")).strip()):
            partial = True
            continue
        if not same_model(row.get("name") or row.get("model"), configured_model):
            continue
        size = positive_integer(row.get("size"))
        vram = positive_integer(row.get("size_vram"), allow_zero=True)
        residency = "unknown"
        if size is not None and vram is not None:
            residency = "gpu" if vram == size else "cpu" if vram == 0 else "mixed" if vram < size else "unknown"
        return {"loaded": True, "runtime_context_length": positive_integer(row.get("context_length")),
                "loaded_size_bytes": size, "size_vram_bytes": vram, "residency": residency,
                "expires_at": row.get("expires_at") if isinstance(row.get("expires_at"), str) else None}
    return {"loaded": None if partial else False, "runtime_context_length": None,
            "loaded_size_bytes": None, "size_vram_bytes": None, "residency": "unknown", "expires_at": None}


def inventory_summary(check, runtime=None, *, runtime_error=None):
    facts = runtime_facts(runtime, check["model"]) if runtime is not None else {
        "loaded": None, "runtime_context_length": None, "loaded_size_bytes": None,
        "size_vram_bytes": None, "residency": "unknown", "expires_at": None}
    return {"configured_model": check["model"], "installed_models": check.get("installed_models", []),
            "capabilities": check.get("capabilities", []), "native_context_length": check.get("native_context_length"),
            "configured_context_length": 16384, **facts, "runtime_probe_available": runtime is not None,
            "runtime_error": runtime_error, "observed_utc": datetime.now(timezone.utc).isoformat(),
            "source": "local_ollama_read_only"}


def describe_inventory(value):
    def number(item):
        return str(item) if item is not None else "non dichiarato"

    def memory(item):
        return f"{item / 1024**3:.2f} GiB" if item is not None else "non verificata"
    loaded = {True: "Caricato", False: "Installato, non caricato", None: "Caricamento non verificato"}[value.get("loaded")]
    place = {"gpu": "GPU", "cpu": "CPU", "mixed": "CPU e GPU", "unknown": "non verificata"}[value.get("residency", "unknown")]
    return (f"Modello: {value.get('configured_model', '—')}\nStato: {loaded}\n"
            f"Esecuzione secondo Ollama: {place}\nVRAM attribuita al modello: {memory(value.get('size_vram_bytes'))}\n"
            f"Contesto nativo dichiarato: {number(value.get('native_context_length'))}\n"
            f"Contesto di esecuzione: {number(value.get('runtime_context_length'))}\n"
            f"Contesto configurato da JARVIS: {number(value.get('configured_context_length'))}\n"
            "Capacità dichiarate: " + (", ".join(value.get("capabilities", [])) or "non disponibili") +
            "\nModelli installati: " + (", ".join(value.get("installed_models", [])) or "non disponibili") +
            "\nVerifica UTC: " + str(value.get("observed_utc", "—")) +
            "\nLa VRAM indicata non è il consumo totale della scheda. Le capacità dichiarate non abilitano nuovi strumenti.")
