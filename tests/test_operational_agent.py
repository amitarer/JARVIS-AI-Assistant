"""Operational requests must reach real tools, ask for missing data and stop safely."""

from dataclasses import replace
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

from jarvis.bootstrap import build_tool_registry
from jarvis.brain.ollama import OllamaProvider
from jarvis.core.models import Cancelled, ToolCall, ToolResult, UserError, UserActionRequired
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import OllamaSettings
from jarvis.tools.whatsapp import WhatsAppMessageTool, WhatsAppContactTool
from jarvis.browser.whatsapp import WhatsAppBrowser
from jarvis.tools.web_reading import WebReadingTool
from jarvis.voice.replies import requests_silence, spoken_reply
from tests.support import make_controller, temporary_project


def response(tool, arguments):
    return {"message": {"content": json.dumps({"tool": tool, "arguments": arguments})}}


def route(kind="task"):
    return {"message": {"content": json.dumps({"request_type": kind, "application": "", "target": "",
            "operations": [], "query": "", "limit": 20, "answer": ""})}}


class OperationalAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = temporary_project()
        self.root = Path(self.temp.name)
        self.controller = make_controller(self.root)
        self.controller.settings = replace(self.controller.settings, ollama=OllamaSettings(enabled=True, max_tool_rounds=8))
        self.controller.tools = build_tool_registry(self.controller.settings, self.controller.repository)
        self.events = []

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, request, responses, approve=True):
        def approval(proposal, context):
            return self.controller.tools.policy.approvals.issue(proposal) if approve else None
        with patch.object(OllamaProvider, "check", return_value={}), \
                patch.object(OllamaProvider, "_json", side_effect=[route(), *responses]):
            self.controller.run({"kind": "chat", "text": request}, threading.Event(), self.events.append, approval)
        return self.controller.repository.tasks()[0]

    def test_two_reads_and_a_launch_continue_until_all_requested_steps_finish(self):
        first, second = self.root / "first.txt", self.root / "second.txt"
        first.write_text("Uno", encoding="utf-8")
        second.write_text("Due", encoding="utf-8")
        with patch.object(self.controller.tools._tools["open_application"], "execute",
                          return_value=ToolResult("Avvio accettato, finestra non verificata.", {"launch_accepted": True})):
            task = self.execute("Apri WhatsApp e leggi entrambi i file", [
                response("open_application", {"application_id": "WhatsApp"}),
                response("inspect_files", {"action": "read_text", "path": str(first)}),
                response("inspect_files", {"action": "read_text", "path": str(second)}),
                response("finish", {"text": "I due file contengono Uno e Due."})])
        self.assertEqual(task["status"], "succeeded")
        self.assertEqual(len(self.controller.repository.operations()), 3)
        self.assertIn("Uno e Due", task["result_text"])

    def test_missing_father_identity_and_message_are_questions_not_fake_success(self):
        service = self.controller.tools._tools["prepare_whatsapp_message"].service
        with patch.object(service, "prepare") as prepare, patch.object(service, "send") as send:
            task = self.execute("Apri WhatsApp e scrivi a mio padre", [
                response("whatsapp_contact", {"action": "lookup", "alias": "mio padre"}),
                response("ask_user", {"text": "Come si chiama tuo padre su WhatsApp e cosa gli scrivo?"})])
        prepare.assert_not_called()
        send.assert_not_called()
        self.assertEqual(task["status"], "waiting_input")
        self.assertIn("cosa gli scrivo", task["result_text"])

    def test_draft_alone_never_sends_and_send_denial_stops_after_draft(self):
        service = self.controller.tools._tools["prepare_whatsapp_message"].service
        prepared = ToolResult("Bozza verificata, non inviata.", {"draft_verified": True, "sent": False})
        with patch.object(service, "prepare", return_value=prepared), patch.object(service, "send") as send:
            task = self.execute("Prepara per Paolo: arrivo", [
                response("prepare_whatsapp_message", {"recipient": "Paolo", "text": "Arrivo"}),
                response("finish", {"text": "Il messaggio resta in bozza."})])
        send.assert_not_called()
        self.assertEqual(task["status"], "succeeded")
        with patch.object(service, "prepare", return_value=prepared), patch.object(service, "send") as send:
            task = self.execute("Invia a Paolo: arrivo", [
                response("send_whatsapp_message", {"recipient": "Paolo", "text": "Arrivo"})], approve=False)
        send.assert_not_called()
        self.assertEqual(task["status"], "failed")

    def test_unregistered_action_is_rejected_before_execution(self):
        task = self.execute("Fai un'azione", [response("run_arbitrary_code", {"command": "anything"})])
        self.assertEqual(task["status"], "failed")
        self.assertEqual(self.controller.repository.operations(), [])

    def test_login_requirement_is_waiting_for_user_and_never_claims_success(self):
        service = self.controller.tools._tools["prepare_whatsapp_message"].service
        with patch.object(service, "prepare", side_effect=UserActionRequired("Collega WhatsApp con il QR.")):
            task = self.execute("Prepara per Paolo: arrivo", [
                response("prepare_whatsapp_message", {"recipient": "Paolo", "text": "Arrivo"})])
        self.assertEqual(task["status"], "waiting_input")
        self.assertTrue(any(e.kind == "response" and "QR" in e.data for e in self.events))

    def test_follow_up_receives_pending_goal_and_does_not_reopen_old_completed_tasks(self):
        self.execute("Scrivi a mio padre", [response("ask_user", {"text": "Cosa gli scrivo?"})])
        seen = []
        def infer(method, path, body, context):
            seen.extend(body["messages"])
            return route() if body["format"]["properties"].get("request_type") else response("ask_user", {"text": "Come si chiama su WhatsApp?"})
        with patch.object(OllamaProvider, "check", return_value={}), patch.object(OllamaProvider, "_json", side_effect=infer):
            self.controller.run({"kind": "chat", "text": "Digli che arrivo tra dieci minuti"}, threading.Event(), self.events.append, lambda *_: None)
        self.assertTrue(any("Incarico" in m.get("content", "") and "Scrivi a mio padre" in m.get("content", "") for m in seen))
        self.assertIn("continued", [t["status"] for t in self.controller.repository.tasks()])

    def test_contact_mapping_persists_and_unknown_alias_is_not_invented(self):
        tool = WhatsAppContactTool(self.controller.repository)
        context = TaskContext("contact", threading.Event(), 5)
        unknown = tool.execute(tool.validate({"action": "lookup", "alias": "mio padre"}), context)
        self.assertFalse(json.loads(unknown.message)["known"])
        tool.execute(tool.validate({"action": "remember", "alias": "mio padre", "name": "Paolo"}), context)
        found = tool.execute(tool.validate({"action": "lookup", "alias": "mio padre"}), context)
        self.assertEqual(json.loads(found.message)["name"], "Paolo")

    def test_web_reading_is_an_observation_not_an_audio_event_or_pdf(self):
        services = Mock()
        services.fetch.return_value = {"url": "https://example.org/", "text": "Contenuto verificato"}
        tool = WebReadingTool(services, "fetch")
        result = tool.execute(tool.validate({"url": "https://example.org/"}), TaskContext("web", threading.Event(), 5))
        self.assertTrue(result.observation)
        self.assertTrue(result.evidence["read_only"])
        services.pdf.assert_not_called()


class WhatsAppSafetyTests(unittest.TestCase):
    def setUp(self):
        browser = Mock()
        browser.target_id = "owned-tab"
        self.service = WhatsAppBrowser(Path.cwd(), browser)
        self.context = TaskContext("whatsapp-task", threading.Event(), 5)
        self.snapshot = {"recipient": "Paolo", "draft": "Arrivo", "matching_outgoing": 0,
                         "send": {"x": 10, "y": 10, "enabled": True}}
        self.service.drafts[self.context.task_id] = {"target_id": "owned-tab", "recipient": "Paolo", "text": "Arrivo"}

    def test_modified_draft_does_not_send_and_cannot_be_retried(self):
        with patch.object(self.service, "observe", return_value={**self.snapshot, "draft": "Testo cambiato"}), \
                patch.object(self.service, "click") as click:
            with self.assertRaisesRegex(UserError, "cambiate"):
                self.service.send("Paolo", "Arrivo", self.context)
            with self.assertRaisesRegex(UserError, "stesso incarico"):
                self.service.send("Paolo", "Arrivo", self.context)
        click.assert_not_called()

    def test_uncertain_send_is_reported_and_not_replayed(self):
        with patch.object(self.service, "observe", return_value=self.snapshot), \
                patch.object(self.service, "wait", return_value={**self.snapshot, "draft": ""}), \
                patch.object(self.service, "click") as click:
            result = self.service.send("Paolo", "Arrivo", self.context)
            self.assertFalse(result.evidence["message_visible"])
            self.assertFalse(result.evidence["delivery_verified"])
            with self.assertRaises(UserError):
                self.service.send("Paolo", "Arrivo", self.context)
        click.assert_called_once()

    def test_stop_prevents_prepared_message_sending(self):
        self.context.cancellation.set()
        with patch.object(self.service, "click") as click, self.assertRaises(Cancelled):
            self.service.send("Paolo", "Arrivo", self.context)
        click.assert_not_called()

    def test_controls_and_sending_parameters_cannot_contain_generated_commands(self):
        tool = WhatsAppMessageTool(self.service)
        for arguments in ({"recipient": "mio padre", "text": "Arrivo"},
                          {"recipient": "Paolo", "text": "Arrivo\nENTER"},
                          {"recipient": "Paolo", "text": "Arrivo", "command": "unexpected"}):
            with self.subTest(arguments=arguments), self.assertRaises(UserError):
                tool.validate(arguments)

    def test_silence_request_and_repeated_follow_up_are_removed(self):
        for request in ("Leggi il sito in silenzio", "Non voglio sentirle", "Leggi senza parlare", "Non leggerlo ad alta voce"):
            self.assertTrue(requests_silence(request), request)
        self.assertFalse(requests_silence("Apri WhatsApp"))
        self.assertEqual(spoken_reply(""), "")
        self.assertEqual(spoken_reply("Pronto. Hai bisogno d'altro?"), "Pronto.")
