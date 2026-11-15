"""A reviewed research plan and task-bound, structured research operations."""

import json
from pathlib import Path

from jarvis.core.models import Risk, ToolCall, ToolResult, UserError
from jarvis.security.sessions import SessionPermission
from jarvis.research.report import validate_report, report_text


RESEARCH_TOOLS = frozenset({"research_search","research_fetch","research_pdf","research_chatgpt","research_google_docs"})


def validate_plan(plan):
    if (not isinstance(plan,dict) or set(plan) != {"topic","queries","use_chatgpt","use_google_docs"}
            or not isinstance(plan["topic"],str) or not 3 <= len(plan["topic"].strip()) <= 1500
            or not isinstance(plan["queries"],list) or not 1 <= len(plan["queries"]) <= 4
            or any(not isinstance(query,str) or not 3 <= len(query.strip()) <= 300 for query in plan["queries"])
            or type(plan["use_chatgpt"]) is not bool or type(plan["use_google_docs"]) is not bool):
        raise UserError("Piano di ricerca non valido: servono argomento, query e servizi richiesti.")
    return {**plan,"topic":plan["topic"].strip(),"queries":[query.strip() for query in plan["queries"]]}


class RunResearchTool:
    name = "run_research"
    risk = Risk.MEDIUM
    description = "Esegui una ricerca completa con fonti web, eventuale ChatGPT e Google Documenti, e consegna un PDF verificato. Il piano concreto richiede una sola conferma iniziale."
    parameters = {"type":"object","properties":{
        "topic":{"type":"string"},"queries":{"type":"array","items":{"type":"string"},"minItems":1,"maxItems":4},
        "use_chatgpt":{"type":"boolean"},"use_google_docs":{"type":"boolean"}},
        "required":["topic","queries","use_chatgpt","use_google_docs"],"additionalProperties":False}

    def validate(self, arguments):
        return validate_plan(arguments)

    def describe(self, arguments):
        return ("Ricerca: "+arguments["topic"]+"\nQuery pubbliche iniziali: "+"; ".join(arguments["queries"])+
                "\nChatGPT: "+("sì" if arguments["use_chatgpt"] else "no")+
                ". Nuovo Google Documento: "+("sì" if arguments["use_google_docs"] else "no")+
                ". Fino a due riformulazioni sullo stesso argomento e una correzione del rapporto prima della consegna PDF in data/reports. "
                "Invii limitati al rapporto; nessuna pubblicazione, nessun file personale letto. STOP sempre disponibile.")

    def execute(self, arguments, context):
        context.checkpoint()
        allowed = {"research_search","research_fetch","research_pdf"}
        if arguments["use_chatgpt"]:
            allowed.add("research_chatgpt")
        if arguments["use_google_docs"]:
            allowed.add("research_google_docs")
        context.session_permission = SessionPermission(context.task_id,context.cancellation,tools=frozenset(allowed))
        context.research_plan = dict(arguments)
        return ToolResult("Ricerca autorizzata: raccolta fonti, stesura e PDF.",{"research_granted":True,"plan":arguments})


class ResearchOperationTool:
    def __init__(self, services, operation):
        self.services = services
        self.name = "research_"+operation
        if self.name not in RESEARCH_TOOLS:
            raise ValueError("Operazione di ricerca non registrata.")
        self.operation = operation
        self.risk = Risk.MEDIUM if operation in {"chatgpt","google_docs"} else Risk.LOW
        self.description = "Passaggio strutturato della ricerca autorizzata: "+operation
        self.parameters = {"type":"object","properties":{},"additionalProperties":False}

    def validate(self, arguments):
        if self.operation == "search":
            expected = {"query"}
        elif self.operation == "fetch":
            expected = {"url"}
        else:
            expected = {"report","sources","folder"}
        if set(arguments) != expected:
            raise UserError("Parametri del passaggio di ricerca non validi.")
        if self.operation in {"search","fetch"}:
            value = arguments[next(iter(expected))]
            if not isinstance(value,str) or not value.strip() or len(value)>4096:
                raise UserError("Query o indirizzo di ricerca non valido.")
        else:
            if not isinstance(arguments["sources"],list):
                raise UserError("Fonti di ricerca non valide.")
            validate_report(arguments["report"],arguments["sources"])
            folder = Path(arguments["folder"])
            if (not folder.is_absolute() or folder.is_symlink() or not folder.resolve().is_relative_to(self.services.root.resolve()/"data/reports")
                    or not folder.is_dir()):
                raise UserError("Cartella di consegna non autorizzata.")
        return dict(arguments)

    def describe(self, arguments):
        return "Passaggio della ricerca approvata: "+self.operation

    def execute(self, arguments, context):
        grant = context.session_permission
        if not isinstance(grant,SessionPermission) or not grant.allows(context,ToolCall(self.name,"{}")):
            raise UserError("Questo passaggio richiede una ricerca autorizzata.")
        context.checkpoint()
        if self.operation == "search":
            data = self.services.search(arguments["query"],context)
        elif self.operation == "fetch":
            data = self.services.fetch(arguments["url"],context)
        elif self.operation == "pdf":
            data = self.services.pdf(arguments["report"],arguments["sources"],Path(arguments["folder"]),context)
        elif self.operation == "chatgpt":
            data = self.services.review_with_chatgpt(arguments["report"],arguments["sources"],context)
        else:
            data = self.services.documents.write_and_export(arguments["report"]["title"],
                report_text(arguments["report"],arguments["sources"]),
                Path(arguments["folder"]),context)
        return ToolResult(json.dumps(data,ensure_ascii=False),data,observation=self.operation in {"search","fetch","chatgpt"})
