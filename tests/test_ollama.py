"""Protocol separation and action evidence regression checks; no real server required."""

from contextlib import contextmanager
from dataclasses import replace
import io
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from jarvis.brain.ollama import OllamaProvider
from jarvis.brain.response_text import FinalTextFilter, final_text
from jarvis.core.models import ToolCall, ToolResult, UserError
from jarvis.core.tasks import TaskContext
from jarvis.core.verified_reply import guard_unverified_answer
from jarvis.infrastructure.settings import OllamaSettings
from tests.support import make_controller, temporary_project


class ResponseSeparationTests(unittest.TestCase):
    def test_reasoning_tags_split_at_every_character_are_removed(self):
        value = "<think>PRIVATE<analysis>ALSO PRIVATE</analysis></think>Risposta finale."
        parser = FinalTextFilter()
        result = "".join(parser.feed(character) for character in value) + parser.finish()
        self.assertEqual(result, "Risposta finale.")

    def test_unclosed_reasoning_is_never_spoken(self):
        self.assertEqual(final_text("<think>PRIVATE"), "")
        self.assertEqual(final_text("Buongiorno.<thi"), "Buongiorno.")

    def test_stream_uses_only_final_content_and_requests_no_thinking(self):
        provider = OllamaProvider(OllamaSettings(enabled=True))
        recorded, chunks = [], []
        rows = [{"model": "qwen3.5:9b", "message": {"thinking": "PRIVATE REASONING", "content": ""}},
                {"message": {"content": "<thi"}}, {"message": {"content": "nk>PRIVATE</think>Ciao, "}},
                {"message": {"content": "Gae."}, "done": True, "eval_count": 12}]

        @contextmanager
        def response(method, path, body, context):
            recorded.append(body)
            yield io.BytesIO(b"".join(json.dumps(row).encode() + b'\n' for row in rows))

        with patch.object(provider, "_response", response):
            text, calls, usage = provider.chat([], [], TaskContext("test", threading.Event(), 10), chunks.append)
        self.assertIs(recorded[0]["think"], False)
        self.assertIs(recorded[0]["stream"], True)
        self.assertEqual(text, "Ciao, Gae.")
        self.assertEqual("".join(chunks), text)
        self.assertNotIn("PRIVATE", str(chunks))
        self.assertGreater(usage["reasoning_characters_discarded"], 0)
        self.assertEqual(calls, [])

    def test_interrupted_stream_never_returns_partial_tool_calls(self):
        provider = OllamaProvider(OllamaSettings())
        @contextmanager
        def response(*_):
            yield io.BytesIO(b'{"message":{"tool_calls":[{"function":{"name":"open_application","arguments":{"application_id":"blocco_note"}}}]}}\n')
        with patch.object(provider, "_response", response), self.assertRaises(UserError):
            provider.chat([], [], TaskContext("test", threading.Event(), 10), lambda _: None)

    def test_false_completion_is_blocked_but_a_negative_answer_is_allowed(self):
        for text in ("Ho aperto Chrome.", "Ho inviato la mail.", "Operazione completata.", "Email inviata.", "Sto aprendo Chrome."):
            with self.subTest(text=text):
                self.assertTrue(guard_unverified_answer(text)[1])
        self.assertFalse(guard_unverified_answer("Non ho inviato la mail.")[1])
        self.assertFalse(guard_unverified_answer("Puoi aprire Blocco note dal menu Start.")[1])


class AgentEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = temporary_project()
        self.controller = make_controller(Path(self.temp.name))
        self.controller.settings = replace(self.controller.settings, ollama=OllamaSettings(enabled=True))

    def tearDown(self):
        self.temp.cleanup()

    def run_task(self, text):
        events = []
        self.controller.run({"kind": "chat", "text": text}, threading.Event(), events.append, lambda *_: None)
        return events

    def test_no_tool_means_no_invented_completion(self):
        with patch.object(OllamaProvider, "check", return_value={"model": "qwen3.5:9b"}), \
             patch.object(OllamaProvider, "chat", return_value=("Ho aperto Chrome.", [], {})):
            events = self.run_task("Apri Chrome")
        final = next(event.data for event in events if event.kind == "response")
        self.assertIn("Non posso confermare", final)
        self.assertEqual(self.controller.repository.operations(), [])

    def test_action_reply_is_derived_from_tool_evidence_not_model_embellishment(self):
        call = ToolCall("open_application", '{"application_id":"blocco_note"}')
        factual = "Processo creato, finestra non verificata."
        tool = self.controller.tools._tools["open_application"]
        with patch.object(OllamaProvider, "check", return_value={"model": "qwen3.5:9b"}), \
             patch.object(OllamaProvider, "chat", side_effect=[("", [call], {}), ("La finestra è verificata e ho inviato una mail.", [], {})]), \
             patch.object(tool, "execute", return_value=ToolResult(factual, {"process_created": True, "window_verified": False})):
            events = self.run_task("Apri Blocco note")
        self.assertEqual(next(event.data for event in events if event.kind == "response"), factual)
        operation = self.controller.repository.operations()[0]
        self.assertEqual(operation["status"], "succeeded")
        self.assertIs(json.loads(operation["evidence_json"])["window_verified"], False)

    def test_failed_tool_never_produces_a_success_response(self):
        call = ToolCall("open_application", '{"application_id":"not_allowed"}')
        with patch.object(OllamaProvider, "check", return_value={"model": "qwen3.5:9b"}), \
             patch.object(OllamaProvider, "chat", return_value=("", [call], {})):
            events = self.run_task("Apri una app non autorizzata")
        self.assertFalse(any(event.kind == "response" for event in events))
        self.assertEqual(self.controller.repository.operations()[0]["status"], "failed")

    def test_only_final_answer_is_persisted_in_sqlite(self):
        with patch.object(OllamaProvider, "check", return_value={"model": "qwen3.5:9b"}), \
             patch.object(OllamaProvider, "chat", return_value=("<think>PRIVATE</think>Risposta italiana.", [], {})):
            self.run_task("Ciao")
        self.assertEqual(self.controller.repository.messages()[-1].content, "Risposta italiana.")
