"""Registered, read-only system information tools chosen by the LLM."""

import json

from jarvis.core.models import Risk, ToolResult, UserError
from jarvis.core.tasks import TaskContext


OPERATIONS = {
    "get_current_datetime": "Leggi ADESSO data e ora reali di Windows, giorno e data in italiano, fuso orario e offset UTC. Usa sempre questo strumento per sapere che ore sono o che giorno e'.",
    "get_system_information": "Leggi Windows reale: nome, versione, build, architettura, nome computer e tempo di attivita'.",
    "get_hardware_information": "Leggi CPU e GPU reali, utilizzo CPU misurato, RAM totale/disponibile e utilizzo, dischi e batteria. Dati non disponibili sono null, mai valori inventati.",
    "get_memory_information": "Leggi RAM attuale totale, disponibile, usata e percentuale di utilizzo da Windows.",
    "get_disk_information": "Leggi unita' locali e spazio disco totale, libero e disponibile all'utente. Non accede automaticamente alle unita' di rete.",
    "get_battery_status": "Leggi presenza batteria, carica, alimentazione e autonomia se Windows le rende disponibili.",
    "get_process_information": "Leggi processi dell'utente nella sessione corrente, memoria e utilizzo CPU campionato. query filtra il nome, limit limita i risultati; nessuna credenziale o riga di comando letta.",
    "get_open_applications": "Elenca finestre e applicazioni aperte, con finestra attiva reale. Sola lettura; le finestre di JARVIS sono escluse.",
}


def number_it(value, digits=2):
    return "non disponibile" if value is None else f"{value:.{digits}f}".replace(".", ",")


def public_system_message(operation, data):
    """Render measured values directly; the model cannot replace them with guesses."""
    if operation == "get_current_datetime":
        return f"Sono le {data['time_it']}. Oggi è {data['weekday_it']} {data['date_it']}."
    if operation == "get_system_information":
        uptime = int(data["uptime_seconds"])
        return (f"{data['os_name']}, {data['architecture']}, versione {data['os_version']}. "
                f"Computer: {data['computer_name']}. Attivo da {uptime // 3600} ore e {uptime % 3600 // 60} minuti.")
    if operation == "get_memory_information":
        return (f"RAM disponibile: {number_it(data['available_gib'])} GiB su {number_it(data['total_gib'])} GiB. "
                f"Utilizzo RAM: {number_it(data['used_percent'])}%.")
    if operation == "get_disk_information":
        return "\n".join(f"{disk['path']}: {number_it(disk['free_gib'])} GiB liberi su {number_it(disk['total_bytes'] / 1024**3)} GiB."
                         if disk["available"] else f"{disk['path']}: {disk['unavailable_reason']}" for disk in data["disks"]) or "Nessuna unità disponibile."
    if operation == "get_battery_status":
        if data["present"] is False:
            return "Windows non rileva una batteria."
        if data["present"] is None:
            return "Lo stato della batteria non è disponibile."
        charge = f"{number_it(data['percent'], 0)}%" if data["percent"] is not None else "non disponibile"
        return f"Carica batteria: {charge}. Alimentazione collegata: " + {True: "sì.", False: "no.", None: "non disponibile."}[data["ac_connected"]]
    if operation == "get_hardware_information":
        cpus = "; ".join(cpu["name"] for cpu in data["processors"]) or "non disponibile"
        gpus = "; ".join(gpu["name"] for gpu in data["graphics_adapters"]) or "non disponibile"
        usage = data["cpu_usage"]["percent"]
        usage_text = f"{number_it(usage)}%" if usage is not None else "non disponibile"
        return (f"CPU: {cpus}. Utilizzo CPU misurato: {usage_text}. GPU: {gpus}. "
                + public_system_message("get_memory_information", data["memory"]))
    if operation == "get_process_information":
        items = [f"{row['name']} (PID {row['process_id']}): {number_it(row['memory_working_set_bytes'] / 1024**2)} MiB di RAM, "
                 + (f"CPU {number_it(row['cpu_percent'])}%" if row['cpu_percent'] is not None else "CPU non disponibile")
                 for row in data["processes"]]
        return ("Processi del tuo utente nella sessione corrente:\n" + "\n".join(items)) if items else "Nessun processo corrispondente accessibile."
    if operation == "get_open_applications":
        active = data["active_window"]
        titles = [window["title"] or window["process_name"] for window in data["windows"]]
        return ("Finestra attiva: " + (active["title"] or active["process_name"] if active else "non disponibile")
                + ". Finestre visibili: " + ("; ".join(titles) if titles else "nessuna") + ".")
    raise ValueError("Operazione di sistema non registrata.")


class SystemInformationTool:
    risk = Risk.LOW

    def __init__(self, service, operation):
        if operation not in OPERATIONS:
            raise ValueError("Operazione SystemInformation non registrata.")
        self.service = service
        self.name = operation
        self.description = OPERATIONS[operation]
        self.parameters = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
        if operation == "get_process_information":
            self.parameters["properties"] = {"query": {"type": "string", "maxLength": 100},
                                             "limit": {"type": "integer", "minimum": 1, "maximum": 50}}

    def validate(self, arguments):
        if self.name != "get_process_information":
            if arguments:
                raise UserError("Questa lettura di sistema non accetta parametri.")
            return {}
        if (set(arguments) - {"query", "limit"} or not isinstance(arguments.get("query", ""), str)
                or len(arguments.get("query", "")) > 100 or "\x00" in arguments.get("query", "")
                or type(arguments.get("limit", 20)) is not int or not 1 <= arguments.get("limit", 20) <= 50):
            raise UserError("Specifica query testuale (massimo 100 caratteri) e limit da 1 a 50.")
        return {"query": arguments.get("query", "").strip(), "limit": arguments.get("limit", 20)}

    def describe(self, arguments):
        return "Consulta informazioni reali di Windows in sola lettura: " + self.name

    def execute(self, arguments, context):
        context.checkpoint()
        tool_context = TaskContext(context.task_id, context.cancellation, min(20, context.remaining))
        result = getattr(self.service, self.name)(tool_context, **arguments)
        context.checkpoint()
        return ToolResult(json.dumps(result, ensure_ascii=False, allow_nan=False),
                          {"source": result["source"], "observed_at_utc": result["observed_at_utc"], "read_only": True},
                          observation=True, public_message=public_system_message(self.name, result))
