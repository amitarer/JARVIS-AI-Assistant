"""Research to a verified artifact, with bounded stages and explicit service evidence."""

import json
import time

from jarvis.brain.ollama import OllamaProvider
from jarvis.core.models import Cancelled, Event, ToolCall, UserError
from jarvis.core.tasks import TaskContext
from jarvis.security.sessions import SessionPermission
from jarvis.research.report import create_job, validate_report, validate_pdf
from jarvis.research.collector import collect_sources


class ResearchExecutor:
    def __init__(self, controller, services):
        self.controller, self.services = controller, services

    def run(self, plan, parent, emit, approve):
        grant = parent.session_permission
        if (not isinstance(grant,SessionPermission) or getattr(parent,"research_plan",None) != plan
                or not grant.allows(parent,ToolCall("research_search","{}"))):
            raise UserError("Serve l'autorizzazione per questo piano di ricerca.")
        session = TaskContext(parent.task_id,parent.cancellation,900,origin=parent.origin)
        folder = create_job(self.controller.settings.root)
        state = {"plan":plan,"sources":[],"searches":[],"completed":[],"status":"running","folder":str(folder)}
        started = time.monotonic()

        def progress(message, **extra):
            state["stage"] = message
            (folder/"stato.json").write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
            parent.partial_result = message+" · cartella lavoro: "+str(folder)
            emit(Event("autonomy",{"active":True,"mode":"research","turns":len(state["sources"]),
                                  "objective":plan["topic"],"stage":message,**extra}))

        def execute(operation, arguments, timeout=40):
            context = TaskContext(parent.task_id,parent.cancellation,min(timeout,session.remaining),origin=parent.origin)
            context.session_permission = grant
            result = self.controller.execute_tool(ToolCall("research_"+operation,json.dumps(arguments,ensure_ascii=False)),
                                                  context,emit,approve)
            return result.evidence

        def wait_ready(check, message):
            while not check():
                session.checkpoint()
                progress(message)
                waiting = time.monotonic()
                parent.cancellation.wait(2)
                session.deadline += time.monotonic()-waiting

        try:
            progress("Preparo il piano di ricerca.")
            provider = OllamaProvider(self.controller.settings.ollama)
            collect_sources(plan,state,provider,execute,session,progress)
            (folder/"fonti.json").write_text(json.dumps(state["sources"],ensure_ascii=False,indent=2),encoding="utf-8")
            state["completed"].append("sources")
            progress("Redigo il rapporto con riferimenti alle fonti raccolte.")
            report = provider.research_report(plan["topic"],state["sources"],session)
            validate_report(report,state["sources"])
            (folder/"rapporto.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
            state["completed"].append("draft")
            arguments = {"report":report,"sources":state["sources"],"folder":str(folder)}
            if plan["use_chatgpt"]:
                self.services.chatgpt.open_chat(session)
                def chat_ready():
                    try:
                        data = self.services.chatgpt.observe(session)
                        return data["composer_ready"] and not data["challenge"] and not data["login_required"]
                    except UserError:
                        return False
                wait_ready(chat_ready,"Bozza pronta. Accedi a ChatGPT nel profilo dedicato per il confronto richiesto. STOP interrompe.")
                progress("Confronto la sintesi con ChatGPT e verifico la risposta.")
                review = execute("chatgpt",arguments,240)
                state["completed"].append("chatgpt")
                (folder/"riscontro-chatgpt.json").write_text(json.dumps(review,ensure_ascii=False,indent=2),encoding="utf-8")
                report = provider.research_report(plan["topic"],state["sources"],session,review=review["review"])
                validate_report(report,state["sources"])
                arguments["report"] = report
            state["reviews"] = []
            for attempt in range(2):
                progress("Revisiono il rapporto confrontando affermazioni e fonti.")
                review = provider.review_report(plan["topic"],report,state["sources"],session)
                state["reviews"].append(review)
                if review["approved"]:
                    break
                if attempt==1:
                    raise UserError("La revisione rileva ancora affermazioni non sostenute dopo la correzione. Rapporto conservato, PDF non consegnato.")
                progress("Correggo i problemi rilevati nella revisione locale.")
                report=provider.research_report(plan["topic"],state["sources"],session,review=json.dumps(review,ensure_ascii=False))
                validate_report(report,state["sources"])
                (folder/"rapporto.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
            report["limitations"].extend(state["reviews"][-1]["notes"])
            if not state["coverage"]["sufficient"]:
                report["limitations"].extend("Copertura parziale: "+gap for gap in state["coverage"]["gaps"])
            if any("MediaWiki" in search.get("engine","") for search in state["searches"]):
                report["limitations"].append("Google non disponibile: individuazione fonti tramite MediaWiki e riferimenti esterni; copertura del web parziale.")
            report["limitations"]=list(dict.fromkeys(report["limitations"]))
            arguments["report"]=report
            (folder/"qualita.json").write_text(json.dumps({"coverage":state["coverage"],"reviews":state["reviews"],"model":self.controller.settings.ollama.model},ensure_ascii=False,indent=2),encoding="utf-8")
            if plan["use_google_docs"]:
                self.services.documents.open_new(session)
                wait_ready(lambda:self.services.documents.ready(session),
                           "Rapporto pronto. Accedi a Google Documenti per creare il nuovo documento richiesto.")
                progress("Scrivo il nuovo Google Documento, verifico il testo esportato e scarico il PDF.")
                artifact = execute("google_docs",arguments,180)
                state["completed"].append("google_docs")
            else:
                progress("Esporto il rapporto in PDF e ne verifico pagine e contenuto.")
                artifact = execute("pdf",arguments,40)
            session.checkpoint()
            from pathlib import Path
            delivered = Path(artifact.get("path","")).resolve()
            if delivered.parent != folder.resolve() or not artifact.get("verified"):
                raise UserError("Il PDF consegnato non corrisponde alla cartella di questa ricerca.")
            if plan["use_google_docs"] and (not artifact.get("google_docs_verified") or not artifact.get("text_export_verified")):
                raise UserError("L'esportazione da Google Documenti non e' verificata.")
            artifact.update(validate_pdf(delivered,expected_title=report["title"]))
            (folder/"rapporto.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
            state.update(status="completed",artifact=artifact,seconds=round(time.monotonic()-started,2))
            state["completed"].append("pdf")
            progress("Ricerca completata: PDF verificato e pronto.")
            parent.deadline = max(parent.deadline,time.monotonic()+5)
            emit(Event("artifact",artifact))
            message = f"Ricerca completata con {len(state['sources'])} fonti consultate. PDF verificato ({artifact['pages']} pagine): {artifact['path']}"
            if not state["coverage"]["sufficient"]:
                message = f"Rapporto con copertura parziale, basato su {len(state['sources'])} fonti. Le lacune sono indicate nel PDF verificato ({artifact['pages']} pagine): {artifact['path']}"
            if artifact.get("document_url"):
                message += "\nGoogle Documento: "+artifact["document_url"]
            return message
        except Cancelled:
            state["status"] = "cancelled"
            raise
        except Exception as exc:
            state["status"] = "incomplete"
            state["error"] = str(exc)
            raise
        finally:
            grant.revoked.set()
            (folder/"stato.json").write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
            emit(Event("autonomy",{"active":False,"mode":"research","turns":len(state["sources"])}))
