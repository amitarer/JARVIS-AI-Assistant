"""Research scope, verified artifacts, cancellation and preserving existing documents."""

import json
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock,patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from jarvis.brain.ollama import OllamaProvider
from jarvis.core.models import Cancelled,ToolCall,UserError
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import OllamaSettings
from jarvis.research.executor import ResearchExecutor
from jarvis.research.google_docs import GoogleDocuments
from jarvis.research.report import export_pdf,validate_pdf,validate_report
from jarvis.research.web import SourceText,public_url,public_get
from jarvis.tools.research import RunResearchTool,ResearchOperationTool,validate_plan
from tests.support import make_controller,temporary_project


PLAN = {"topic":"Un argomento scientifico","queries":["argomento scientifico"],"use_chatgpt":False,"use_google_docs":False}
SOURCES = [{"id":n,"title":f"Fonte {n}","url":f"https://example.org/source{n}","text":f"Osservazione indipendente numero {n}. "*20,"retrieved_at_utc":"2026-11-14"} for n in (1,2)]
REPORT = {"title":"Rapporto scientifico verificato","summary":"Sintesi con fatti documentati.","sections":[
    {"heading":"Osservazioni","paragraphs":["Un fatto osservato e verificabile."],"source_ids":[1,2]}],"limitations":["Campione limitato."]}


class ResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        for font in ("segoeui.ttf","segoeuib.ttf"):
            QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts")/font))

    def setUp(self):
        self.temp = temporary_project()
        self.root = Path(self.temp.name)
        self.controller = make_controller(self.root)
        self.controller.repository.create_task("research-test","research")
        self.context = TaskContext("research-test",threading.Event(),30)
        self.services = Mock(root=self.root)
        self.services.search.return_value = {"results":[{"url":s["url"]} for s in SOURCES],"engine":"fixture"}
        self.services.fetch.side_effect = lambda url,ctx:dict(next(s for s in SOURCES if s["url"]==url))
        self.services.pdf.side_effect = export_pdf
        self.controller.tools.register(RunResearchTool())
        for operation in ("search","fetch","pdf","chatgpt","google_docs"):
            self.controller.tools.register(ResearchOperationTool(self.services,operation))
        self.events = []
        self.approvals = []

    def tearDown(self):
        self.temp.cleanup()

    def approve(self,request,ctx):
        self.approvals.append(request.call.name)
        return self.controller.tools.policy.approvals.issue(request)

    def authorize(self,plan=PLAN):
        self.controller.execute_tool(ToolCall("run_research",json.dumps(plan)),self.context,self.events.append,self.approve)

    def run_job(self,plan=PLAN,emit=None,coverage=None,reviews=None):
        with patch.object(OllamaProvider,"relevant_sources",side_effect=lambda topic,sources,context:sources), \
                patch.object(OllamaProvider,"assess_research",side_effect=coverage or [{"sufficient":True,"gaps":[],"queries":[]}]), \
                patch.object(OllamaProvider,"review_report",side_effect=reviews or [{"approved":True,"issues":[],"notes":[]}]), \
                patch.object(OllamaProvider,"research_report",return_value=json.loads(json.dumps(REPORT))):
            return ResearchExecutor(self.controller,self.services).run(plan,self.context,emit or self.events.append,self.approve)

    def test_plan_and_citation_validation_reject_guessed_references(self):
        self.assertEqual(validate_plan(PLAN),PLAN)
        with self.assertRaises(UserError):
            validate_plan({**PLAN,"use_google_docs":"yes"})
        invalid = json.loads(json.dumps(REPORT))
        invalid["sections"][0]["source_ids"] = [99]
        with self.assertRaises(UserError):
            validate_report(invalid,SOURCES)

    def test_unapproved_job_has_no_effects(self):
        with self.assertRaises(UserError):
            self.run_job()
        self.services.search.assert_not_called()

    def test_scope_cannot_send_to_unrequested_services(self):
        self.authorize()
        folder = self.root/"data/reports/test"
        folder.mkdir(parents=True)
        call = ToolCall("research_chatgpt",json.dumps({"report":REPORT,"sources":SOURCES,"folder":str(folder)}))
        with self.assertRaises(UserError):
            self.controller.tools.execute(call,self.context,lambda *_:None)
        self.services.review_with_chatgpt.assert_not_called()
        names = {s["name"] for s in self.controller.tools.schemas(for_model=True)}
        self.assertIn("run_research",names)
        self.assertFalse(any(n.startswith("research_") for n in names))

    def test_finite_job_delivers_pdf_only_after_reopening_actual_file(self):
        self.authorize()
        message = self.run_job()
        artifact = next(e.data for e in self.events if e.kind=="artifact")
        self.assertTrue(validate_pdf(artifact["path"],expected_title=REPORT["title"])["verified"])
        self.assertIn("PDF verificato",message)
        self.assertEqual(self.approvals,["run_research"])
        self.assertTrue(self.context.session_permission.revoked.is_set())
        state = json.loads((Path(artifact["path"]).parent/"stato.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"],"completed")

    def test_stop_between_stages_does_not_deliver_or_write_pdf(self):
        self.authorize()
        def emit(event):
            self.events.append(event)
            if event.kind=="autonomy" and event.data.get("stage","").startswith("Leggo e confronto"):
                self.context.cancellation.set()
        with self.assertRaises(Cancelled):
            self.run_job(emit=emit)
        self.services.pdf.assert_not_called()
        self.assertFalse(any(e.kind=="artifact" for e in self.events))
        self.assertTrue(self.context.session_permission.revoked.is_set())

    def test_failed_google_export_cannot_report_completion_or_fallback_silently(self):
        plan = {**PLAN,"use_google_docs":True}
        self.services.documents.ready.return_value = True
        self.services.documents.write_and_export.side_effect = UserError("Esportazione non verificata")
        self.authorize(plan)
        with self.assertRaisesRegex(UserError,"Esportazione"):
            self.run_job(plan)
        self.services.pdf.assert_not_called()
        self.assertFalse(any(e.kind=="artifact" for e in self.events))
        state = json.loads(next((self.root/"data/reports").glob("*/stato.json")).read_text(encoding="utf-8"))
        self.assertEqual(state["status"],"incomplete")

    def test_fake_or_unreadable_pdf_is_not_delivered(self):
        self.authorize()
        def fake(report,sources,folder,ctx):
            path=folder/"ricerca.pdf"
            path.write_bytes(b"not a PDF")
            return {"verified":True,"path":str(path),"pages":1}
        self.services.pdf.side_effect = fake
        with self.assertRaises(UserError):
            self.run_job()
        self.assertFalse(any(e.kind=="artifact" for e in self.events))

    def test_existing_google_doc_title_is_never_modified(self):
        documents = GoogleDocuments(self.root)
        documents.browser._evaluate = Mock(return_value={"ready":True,"title":"Documento personale","url":"https://docs.google.com/document/d/abc/edit"})
        documents.browser._call = Mock()
        with self.assertRaisesRegex(UserError,"esistente"):
            documents.ready(self.context)
        documents.browser._call.assert_not_called()

    def test_nonempty_untitled_google_doc_is_preserved(self):
        documents = GoogleDocuments(self.root)
        documents.document_id = "abc"
        documents.ready = Mock(return_value=True)
        documents.browser._call = Mock()
        folder = self.root/"data/reports/test"
        folder.mkdir(parents=True)
        text = folder/"existing.txt"
        text.write_text("Testo gia' presente",encoding="utf-8")
        documents._download = Mock(return_value=text)
        with self.assertRaisesRegex(UserError,"gia' del testo"):
            documents.write_and_export("Titolo","Nuovo testo",folder,self.context)
        self.assertFalse(any(call.args[0]=="Input.insertText" for call in documents.browser._call.call_args_list))

    def test_private_addresses_and_rebinding_are_rejected_before_connection(self):
        for url in ("file:///C:/secret","http://127.0.0.1/","http://169.254.169.254/","http://user:pass@example.org/"):
            with self.assertRaises(UserError):
                public_url(url)
        with patch("jarvis.research.web.socket.getaddrinfo",side_effect=[[(2,1,6,"",("8.8.8.8",443))],[(2,1,6,"",("127.0.0.1",443))]]), \
                patch("jarvis.research.web.socket.socket") as connect:
            with self.assertRaises(UserError):
                public_get("https://example.org/",self.context)
            connect.assert_not_called()

    def test_main_content_excludes_navigation_and_scripts(self):
        parser = SourceText()
        parser.feed('<header>Menu</header><main><h1>Titolo</h1><p>Dato utile</p><script>ignore()</script></main><footer>Footer</footer>')
        self.assertIn("Dato utile"," ".join(parser.main_parts))
        self.assertNotIn("Menu"," ".join(parser.main_parts))
        self.assertNotIn("ignore()"," ".join(parser.main_parts))

    def test_missing_topic_is_returned_as_question_before_any_job(self):
        provider = OllamaProvider(OllamaSettings())
        with patch.object(provider,"_json",return_value={"message":{"content":json.dumps({**PLAN,"topic_present":False})}}):
            with self.assertRaisesRegex(UserError,"quale argomento"):
                provider.plan_research("Fammi un PDF su questa cosa",self.context)

    def test_failed_initial_search_is_reformulated_within_same_approval(self):
        self.services.search.side_effect=[UserError("Nessun risultato"),{"results":[{"url":s["url"]} for s in SOURCES],"engine":"fixture"}]
        self.authorize()
        self.run_job(coverage=[{"sufficient":False,"gaps":["Mancano fonti"],"queries":["nuova query pertinente"]},
                               {"sufficient":True,"gaps":[],"queries":[]}])
        self.assertEqual(self.services.search.call_count,2)
        self.assertEqual(self.approvals,["run_research"])
        self.assertTrue(any(e.kind=="autonomy" and "Riformulo" in e.data.get("stage","") for e in self.events))

    def test_copied_pages_do_not_count_as_independent_sources(self):
        self.services.fetch.side_effect=lambda url,ctx:{**SOURCES[0],"url":url}
        self.authorize()
        with self.assertRaisesRegex(UserError,"fonti distinte"):
            self.run_job(coverage=[{"sufficient":False,"gaps":["Una sola fonte"],"queries":[]}])
        self.services.pdf.assert_not_called()

    def test_report_is_revised_once_then_checked_again(self):
        self.authorize()
        self.run_job(reviews=[{"approved":False,"issues":["Correggi una cifra"],"notes":[]},
                              {"approved":True,"issues":[],"notes":["Dato storico."]}])
        artifact=next(e.data for e in self.events if e.kind=="artifact")
        state=json.loads((Path(artifact["path"]).parent/"stato.json").read_text(encoding="utf-8"))
        self.assertEqual(len(state["reviews"]),2)
        self.assertTrue(state["reviews"][-1]["approved"])

    def test_persistent_review_issues_block_pdf_and_external_document_creation(self):
        plan={**PLAN,"use_google_docs":True}
        self.authorize(plan)
        rejected={"approved":False,"issues":["Affermazione non sostenuta"],"notes":[]}
        with self.assertRaisesRegex(UserError,"ancora affermazioni"):
            self.run_job(plan,reviews=[rejected,rejected])
        self.services.documents.open_new.assert_not_called()
        self.services.pdf.assert_not_called()
        self.assertFalse(any(e.kind=="artifact" for e in self.events))

    def test_partial_coverage_is_explicit_in_delivered_report(self):
        self.authorize()
        message=self.run_job(coverage=[{"sufficient":False,"gaps":["Dati recenti non disponibili"],"queries":[]}])
        self.assertIn("copertura parziale",message)
        artifact=next(e.data for e in self.events if e.kind=="artifact")
        report=json.loads((Path(artifact["path"]).parent/"rapporto.json").read_text(encoding="utf-8"))
        self.assertIn("Copertura parziale: Dati recenti non disponibili",report["limitations"])

    def test_stop_during_replanning_prevents_next_search(self):
        self.authorize()
        def emit(event):
            self.events.append(event)
            if event.kind=="autonomy" and "Riformulo" in event.data.get("stage",""):
                self.context.cancellation.set()
        with self.assertRaises(Cancelled):
            self.run_job(emit=emit,coverage=[{"sufficient":False,"gaps":["Dati incompleti"],"queries":["nuova ricerca"]}])
        self.assertEqual(self.services.search.call_count,1)
        self.services.pdf.assert_not_called()

    def test_reviewer_cannot_approve_and_report_errors_simultaneously(self):
        from jarvis.research.quality import validate_review
        with self.assertRaises(UserError):
            validate_review({"approved":True,"issues":["Errore"],"notes":[]})

    def test_malformed_review_retries_only_the_model_evaluation(self):
        provider=OllamaProvider(OllamaSettings())
        with patch.object(provider,"_json",side_effect=[{"message":{"content":'{"approved":'}},
                {"message":{"content":json.dumps({"issues":[],"notes":[]})}}]) as call:
            reviewed=provider.review_report(PLAN["topic"],REPORT,SOURCES,self.context)
        self.assertTrue(reviewed["approved"])
        self.assertEqual(call.call_count,2)

    def test_reviewer_cannot_invent_report_or_source_quotes(self):
        from jarvis.research.quality import grounded_review
        review={"issues":[{"claim":"Il rapporto non contiene questa frase","source_id":1,"evidence":"Osservazione indipendente numero 1.","reason":"La fonte dice altro"}],"notes":[]}
        with self.assertRaisesRegex(UserError,"passaggio non presente"):
            grounded_review(review,REPORT,SOURCES)

    def test_identical_quote_is_not_evidence_of_a_contradiction(self):
        from jarvis.research.quality import grounded_review
        report=json.loads(json.dumps(REPORT))
        report["summary"]=SOURCES[0]["text"].split(". ")[0]+"."
        reviewed=grounded_review({"issues":[{"claim":report["summary"],"source_id":1,"evidence":report["summary"],"reason":"Confronto identico senza differenze"}],"notes":[]},report,SOURCES)
        self.assertTrue(reviewed["approved"])

    def test_read_recovery_cannot_choose_a_write_tool(self):
        provider=OllamaProvider(OllamaSettings())
        schema=[{"name":"inspect_files","parameters":{"type":"object","properties":{}},"description":"Leggi file"}]
        with patch.object(provider,"_json",return_value={"message":{"content":json.dumps({"tool":"desktop_action","arguments":{}})}}):
            with self.assertRaisesRegex(UserError,"recupero"):
                provider.recover_read([{"role":"user","content":"Leggi un file"}],schema,ToolCall("inspect_files",'{}'),self.context)


if __name__=="__main__":
    unittest.main()
