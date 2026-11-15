"""Task-scoped authorization, stopping, bounded steps and uncertain submission."""

import json
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

from jarvis.brain.ollama import OllamaProvider
from jarvis.core.models import Cancelled, ToolCall, UserError
from jarvis.core.task_executor import TaskExecutor
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import OllamaSettings
from jarvis.security.approvals import ApprovalStore
from jarvis.security.policy import SecurityPolicy
from jarvis.security.sessions import SessionPermission
from jarvis.tools.autonomy import BrowserChatTool, StartAutonomousChatTool
from jarvis.tools.registry import ToolRegistry
from jarvis.browser.controller import BrowserController
from tests.support import make_controller, temporary_project


class AutonomyTests(unittest.TestCase):
    def setUp(self):
        self.context = TaskContext("session", threading.Event(), 10)
        self.browser = Mock()
        self.browser.send.return_value = {"submitted": True, "assistant_baseline": 0}
        self.registry = ToolRegistry(SecurityPolicy(ApprovalStore()))
        for operation in ("open", "observe", "send", "reply"):
            self.registry.register(BrowserChatTool(self.browser, operation))
        self.registry.register(StartAutonomousChatTool())

    def authorize_objective(self, controller, objective):
        if "start_autonomous_chat" not in controller.tools:
            controller.tools.register(StartAutonomousChatTool())
        controller.tools.execute(ToolCall("start_autonomous_chat", json.dumps({"objective":objective})), self.context,
            lambda request, context: controller.tools.policy.approvals.issue(request))

    def test_executor_cannot_start_without_approved_objective(self):
        controller = Mock()
        with self.assertRaisesRegex(UserError, "autorizzazione iniziale"):
            TaskExecutor(controller).run_chat("Obiettivo non approvato", self.context, lambda *_:None, lambda *_:None)
        controller.execute_tool.assert_not_called()

    def test_start_requires_exact_initial_approval(self):
        with self.assertRaises(UserError):
            self.registry.execute(ToolCall("start_autonomous_chat", '{"objective":"Parla di scienza"}'), self.context, lambda *_: None)
        self.browser.open_chat.assert_not_called()

    def test_browser_send_without_a_session_cannot_execute_even_after_single_approval(self):
        def approve(request, context):
            return self.registry.policy.approvals.issue(request)
        with self.assertRaisesRegex(UserError, "sessione"):
            self.registry.execute(ToolCall("browser_chat_send", '{"text":"Ciao"}'), self.context, approve)
        self.browser.send.assert_not_called()

    def test_authorized_session_can_send_without_repeated_prompts_and_is_task_bound(self):
        grant = SessionPermission("session", self.context.cancellation)
        self.context.session_permission = grant
        call = ToolCall("browser_chat_send", '{"text":"Ciao"}')
        result = self.registry.execute(call, self.context, lambda *_: self.fail("No per-message approval"))
        self.assertTrue(result.evidence["submitted"])
        other = TaskContext("different", self.context.cancellation, 10)
        other.session_permission = grant
        with self.assertRaises(UserError):
            self.registry.execute(call, other, lambda *_: None)

    def test_session_grant_does_not_authorize_unrelated_pc_operations(self):
        grant = SessionPermission("session", self.context.cancellation)
        for name in ("desktop_action", "open_application", "clear_history", "run_powershell"):
            self.assertFalse(grant.allows(self.context, ToolCall(name, "{}")))

    def test_browser_refuses_navigation_outside_approved_origin_before_typing(self):
        with temporary_project() as directory:
            browser = BrowserController(Path(directory))
            browser.port = 1234
            browser.target_id = "owned-tab"
            with patch.object(browser, "_http", return_value=[{"id":"owned-tab","url":"https://other.example/"}]), \
                    patch.object(browser, "_transport") as transport, self.assertRaises(UserError):
                browser.send("Ciao", self.context)
            transport.assert_not_called()

    def test_revocation_immediately_before_effect_prevents_send(self):
        grant = SessionPermission("session", self.context.cancellation)
        self.context.session_permission = grant
        with self.assertRaisesRegex(UserError, "revocata"):
            self.registry.execute(ToolCall("browser_chat_send", '{"text":"Ciao"}'), self.context,
                                  lambda *_: None, before_execute=grant.revoked.set)
        self.browser.send.assert_not_called()

    def test_stop_prevents_new_send_and_private_browser_tools_are_hidden_from_model(self):
        self.context.session_permission = SessionPermission("session", self.context.cancellation)
        self.context.cancellation.set()
        with self.assertRaises(Cancelled):
            self.registry.execute(ToolCall("browser_chat_send", '{"text":"Ciao"}'), self.context, lambda *_: None)
        self.browser.send.assert_not_called()
        names = [schema["name"] for schema in self.registry.schemas(for_model=True)]
        self.assertEqual(names, ["start_autonomous_chat"])

    def test_selector_distinguishes_chat_session_from_opening_website(self):
        provider = OllamaProvider(OllamaSettings(enabled=True))
        schema = [{"name":"get_current_datetime","description":"Clock"},
                  {"name":"start_autonomous_chat","description":"Sessione fino a STOP"}]
        response = {"request_type":"autonomous_chat","target":"Conversazione sulla scienza",
                    "application":"","operations":[],"query":"","limit":20}
        with patch.object(provider, "_json", return_value={"message":{"content":json.dumps(response)}}):
            calls = provider.select_initial_tools([{"role":"user","content":"Inizia a chattare con ChatGPT fino a stop"}], schema, self.context)
        self.assertEqual(calls, [ToolCall("start_autonomous_chat", json.dumps({"objective":"Conversazione sulla scienza"}))])

    def test_uncertain_send_is_not_retried(self):
        with temporary_project() as directory:
            controller = make_controller(Path(directory))
            controller.repository.create_task("session", "autonomous")
            browser = Mock()
            browser.open_chat.return_value = {"opened": True}
            browser.observe.return_value = {"composer_ready":True,"challenge":False,"login_required":False,"busy":False,"draft":""}
            browser.send.side_effect = UserError("Invio non verificato")
            for operation in ("open", "observe", "send", "reply"):
                controller.tools.register(BrowserChatTool(browser, operation))
            self.authorize_objective(controller, "Scienza")
            def emit(event):
                if event.kind == "autonomy" and event.data.get("stage", "").startswith("Invio sospeso"):
                    self.context.cancellation.set()
            with patch.object(OllamaProvider, "chat", return_value=("Una domanda", [], {})), self.assertRaises(Cancelled):
                TaskExecutor(controller).run_chat("Scienza", self.context, emit, lambda *_: None)
            self.assertEqual(browser.send.call_count, 1)
            browser.wait_reply.assert_not_called()

    def test_session_continues_beyond_original_task_deadline_and_revokes_grant_on_stop(self):
        with temporary_project() as directory:
            controller = make_controller(Path(directory))
            controller.repository.create_task("session", "autonomous")
            browser = Mock()
            browser.open_chat.return_value = {"opened":True}
            browser.observe.return_value = {"composer_ready":True,"challenge":False,"login_required":False,"busy":False,"draft":""}
            browser.send.return_value = {"submitted":True,"assistant_baseline":0}
            browser.wait_reply.return_value = {"reply":"Risposta verificata","reply_verified":True}
            for operation in ("open", "observe", "send", "reply"):
                controller.tools.register(BrowserChatTool(browser, operation))
            self.authorize_objective(controller, "Scienza")
            self.context.deadline = 0  # The original ordinary-task deadline has already passed.
            def emit(event):
                if event.kind == "autonomy" and event.data.get("last_reply") and event.data["turns"] == 2:
                    self.context.cancellation.set()
            with patch.object(OllamaProvider, "chat", side_effect=[("Domanda uno", [], {}),("Domanda due", [], {})]), \
                    patch.object(self.context.cancellation, "wait", return_value=False), self.assertRaises(Cancelled):
                TaskExecutor(controller).run_chat("Scienza", self.context, emit, lambda *_: None)
            self.assertEqual(browser.send.call_count, 2)
            grant = browser.send.call_args.args[1].session_permission
            self.assertTrue(grant.revoked.is_set())
            self.assertIn("2 messaggi", self.context.partial_result)
