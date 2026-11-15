"""The one-inference response must retain verification and tool boundaries."""

from dataclasses import replace
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from jarvis.bootstrap import build_tool_registry
from jarvis.brain.ollama import OllamaProvider
from jarvis.core.models import UserError
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import OllamaSettings
from tests.support import make_controller, temporary_project


def selection(answer):
    return {"request_type": "conversation", "application": "", "target": "", "operations": [],
            "query": "", "limit": 20, "answer": answer}


class FastConversationTests(unittest.TestCase):
    def run_conversation(self, answer):
        with temporary_project() as temporary:
            controller = make_controller(Path(temporary))
            controller.settings = replace(controller.settings, ollama=OllamaSettings(enabled=True))
            controller.tools = build_tool_registry(controller.settings, controller.repository)
            events = []
            with patch.object(OllamaProvider, "check", return_value={}), \
                 patch.object(OllamaProvider, "_json", return_value={"message": {"content": json.dumps(selection(answer))}}) as inference, \
                 patch.object(OllamaProvider, "chat") as second_inference:
                controller.run({"kind": "chat", "text": "Ciao"}, threading.Event(), events.append, lambda *_: None)
            second_inference.assert_not_called()
            self.assertEqual(inference.call_count, 1)
            self.assertEqual(controller.repository.operations(), [])
            return events, controller.repository.messages()[-1].content

    def test_direct_response_uses_one_inference_and_filters_private_reasoning(self):
        events, saved = self.run_conversation("<think>PRIVATE</think>Buongiorno.")
        self.assertEqual(saved, "Buongiorno.")
        self.assertEqual(next(event.data for event in events if event.kind == "response"), saved)
        self.assertNotIn("PRIVATE", str(events))

    def test_direct_response_cannot_claim_unexecuted_actions(self):
        events, saved = self.run_conversation("Ho inviato la mail.")
        self.assertIn("Non posso confermare", saved)
        self.assertTrue(any(event.kind == "verification" for event in events))

    def test_conversation_cannot_smuggle_a_tool_or_unknown_field(self):
        provider = OllamaProvider(OllamaSettings(enabled=True))
        for value in ({**selection("Ciao"), "operations": ["get_current_datetime"]},
                      {**selection("Ciao"), "command": "unexpected"},
                      {**selection("Ciao"), "answer": {"execute": "unexpected"}}):
            with self.subTest(value=value), patch.object(provider, "_json", return_value={"message": {"content": json.dumps(value)}}):
                with self.assertRaises(UserError):
                    provider.select_initial_tools([{"role": "user", "content": "Ciao"}],
                        [{"name": "get_current_datetime", "description": "Clock"}], TaskContext("test", threading.Event(), 5))
