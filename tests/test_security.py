import threading
import time
import unittest
from pathlib import Path

from jarvis.core.models import ApprovalRequest, Cancelled, Risk, ToolCall, UserError
from jarvis.core.tasks import TaskContext
from jarvis.security.approvals import ApprovalStore
from jarvis.security.policy import canonical_call
from tests.support import make_controller, temporary_project


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.store = ApprovalStore()
        self.call = canonical_call("send_message", {"to": "person", "text": "draft"})
        self.request = ApprovalRequest("task-a", self.call, Risk.HIGH, "Send this draft")

    def test_approval_is_single_use(self):
        token = self.store.issue(self.request)
        self.store.consume(token, "task-a", self.call, Risk.HIGH)
        with self.assertRaises(UserError):
            self.store.consume(token, "task-a", self.call, Risk.HIGH)

    def test_change_of_parameters_task_or_risk_cannot_reuse_grant(self):
        for task, call, risk in (("other-task", self.call, Risk.HIGH),
                                  ("task-a", canonical_call("send_message", {"to": "other"}), Risk.HIGH),
                                  ("task-a", self.call, Risk.MEDIUM)):
            with self.subTest(task=task, call=call, risk=risk):
                token = self.store.issue(self.request)
                with self.assertRaises(UserError):
                    self.store.consume(token, task, call, risk)

    def test_expired_and_revoked_grants_fail_closed(self):
        token = self.store.issue(self.request, ttl=-1)
        with self.assertRaises(UserError):
            self.store.consume(token, "task-a", self.call, Risk.HIGH)
        token = self.store.issue(self.request)
        self.store.revoke_all()
        with self.assertRaises(UserError):
            self.store.consume(token, "task-a", self.call, Risk.HIGH)

    def test_json_key_order_does_not_change_action_identity(self):
        self.assertEqual(canonical_call("tool", {"a": 1, "b": 2}), canonical_call("tool", {"b": 2, "a": 1}))


class ToolBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = temporary_project()
        self.controller = make_controller(Path(self.temp.name))
        self.context = TaskContext("test-task", threading.Event(), 5)
        self.controller.repository.create_task("test-task", "test")

    def tearDown(self):
        self.temp.cleanup()

    def test_unknown_tool_is_denied(self):
        with self.assertRaises(UserError):
            self.controller.tools.execute(ToolCall("run_shell", '{}'), self.context, lambda *_: None)

    def test_invalid_json_and_non_object_are_denied(self):
        for args in ("not-json", "[]", "null"):
            with self.subTest(args=args), self.assertRaises(UserError):
                self.controller.tools.execute(ToolCall("open_application", args), self.context, lambda *_: None)

    def test_history_cannot_be_deleted_without_exact_approval(self):
        repository = self.controller.repository
        repository.add_message("user", "keep this")
        with self.assertRaises(UserError):
            self.controller.tools.execute(ToolCall("clear_history", "{}"), self.context, lambda *_: None)
        self.assertEqual(repository.messages()[0].content, "keep this")

    def test_cancellation_after_confirmation_prevents_deletion(self):
        self.controller.repository.add_message("user", "keep this")
        def approve(request, context):
            token = self.controller.tools.policy.approvals.issue(request)
            context.cancellation.set()
            return token
        with self.assertRaises(Cancelled):
            self.controller.tools.execute(ToolCall("clear_history", "{}"), self.context, approve)
        self.assertEqual(len(self.controller.repository.messages()), 1)

    def test_concrete_approval_permits_deletion_and_preserves_preferences(self):
        repository = self.controller.repository
        repository.add_message("user", "delete this")
        repository.save_preferences(True, "WARNING")
        def approve(request, context):
            self.assertEqual(request.call, ToolCall("clear_history", "{}"))
            self.assertEqual(request.risk, Risk.HIGH)
            return self.controller.tools.policy.approvals.issue(request)
        result = self.controller.tools.execute(ToolCall("clear_history", "{}"), self.context, approve)
        self.assertTrue(result.evidence["history_cleared"])
        self.assertEqual(repository.messages(), [])
        self.assertEqual(repository.preferences()["log_level"], "WARNING")
