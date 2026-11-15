"""Bounded working memory for tool recovery and progress, without replaying effects."""

import hashlib
import json
from jarvis.core.models import UserError


READ_ONLY_TOOLS=frozenset({"get_current_datetime","get_system_information","get_hardware_information",
    "get_memory_information","get_disk_information","get_battery_status","get_process_information",
    "get_open_applications","list_applications","inspect_files","inspect_desktop","read_operations", "search_web", "read_web_page"})


class WorkingMemory:
    def __init__(self):
        self.steps=0
        self.failures={}
        self.unchanged={}
        self.last_error=""
        self.failed_call=None
        self.needs_file_content=False

    def failure(self,call,error):
        key=self.key(call)
        self.failures[key]=self.failures.get(key,0)+1
        self.last_error=str(error)
        self.failed_call=call
        if call.name=="inspect_files" and json.loads(call.arguments_json).get("action")=="read_text":
            self.needs_file_content=True
        if self.failures[key]>=2 or sum(self.failures.values())>=4:
            raise UserError("Il recupero delle letture non sta facendo progressi. Ultimo errore: "+str(error))

    def observed(self,call,result):
        self.steps+=1
        self.last_error=""
        if call.name=="inspect_files" and json.loads(call.arguments_json).get("action")=="read_text":
            self.needs_file_content=False
        if call.name not in READ_ONLY_TOOLS:
            self.unchanged.clear()
            return
        fingerprint=hashlib.sha256((self.key(call)+result.message+json.dumps(result.evidence,sort_keys=True)).encode()).hexdigest()
        self.unchanged[fingerprint]=self.unchanged.get(fingerprint,0)+1
        if self.unchanged[fingerprint]>=3:
            raise UserError("La stessa lettura e' stata ripetuta senza nuovi risultati. Attivita' arrestata per evitare un ciclo.")

    @staticmethod
    def key(call):
        try:
            return call.name+json.dumps(json.loads(call.arguments_json),sort_keys=True,ensure_ascii=False)
        except (ValueError,TypeError):
            return call.name+str(call.arguments_json)


def compact_observations(messages):
    """Keep recent evidence, with explicit excerpts for stale tool outputs."""
    indices=[index for index,m in enumerate(messages) if m["role"]=="tool"]
    recent=set(indices[-2:])
    latest=indices[-1] if indices else None
    result=[]
    for index,message in enumerate(messages):
        content=message.get("content","")
        limit=20000 if index==latest else 7000 if index in recent else 1000
        if message["role"]=="tool" and limit and len(content)>limit:
            message={**message,"content":json.dumps({"truncated":True,"excerpt":content[:limit],
                "note":"Osservazione abbreviata; rileggi lo strumento se servono dettagli mancanti."},ensure_ascii=False)}
        result.append(message)
    return result
