"""Spoken URL resolution, follow-up replies and wake/re-arm regressions."""

import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from jarvis.brain.ollama import OllamaProvider
from jarvis.core.models import Risk, ToolCall, UserError
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import OllamaSettings
from jarvis.security.approvals import ApprovalStore
from jarvis.security.policy import SecurityPolicy
from jarvis.tools.pc import OpenResourceTool
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.websites import WebsiteCatalog
from jarvis.voice.replies import spoken_reply
from jarvis.voice.session import spoken_control
from jarvis.voice.wake_word import ActivationGate
from tests.support import temporary_project, populate


class VoiceAndWebsiteTests(unittest.TestCase):
    def test_wake_detects_classifier_peak_on_quiet_tail_of_spoken_word(self):
        gate = ActivationGate(0.95)
        self.assertFalse(gate.feed(0.001, 0.02, 1.0))
        self.assertTrue(gate.feed(0.373, 0.000638, 1.32))

    def test_classifier_peak_without_recent_voice_is_not_a_wake(self):
        gate = ActivationGate(0.95)
        self.assertFalse(gate.feed(0.8, 0.0001, 1))
        self.assertFalse(gate.feed(0.01, 0.02, 2))
        self.assertFalse(gate.feed(0.8, 0.0001, 3))

    def test_wake_respects_cooldown_and_reset_drops_old_audio_energy(self):
        gate = ActivationGate(0.95)
        self.assertTrue(gate.feed(0.8, 0.02, 1))
        self.assertFalse(gate.feed(0.8, 0.02, 1.5))
        gate.reset()
        self.assertFalse(gate.feed(0.8, 0.0001, 4))
        self.assertTrue(gate.feed(0.8, 0.02, 4.1))

    def test_spoken_follow_up_is_added_once_and_decline_ends_conversation(self):
        message = spoken_reply("Chrome avviato.")
        self.assertEqual(message, "Chrome avviato.\nHa bisogno d'altro, signore?")
        self.assertEqual(spoken_reply(message), message)
        self.assertEqual(spoken_control("No, grazie."), "chiudi")
        self.assertEqual(spoken_control("Jarvis, basta."), "chiudi")
        self.assertIsNone(spoken_control("Apri la cartella grazie"))

    def test_long_spoken_result_preserves_follow_up_inside_tts_limit(self):
        text = spoken_reply("Dettaglio. " * 400)
        self.assertLessEqual(len(text), 2000)
        self.assertTrue(text.endswith("Ha bisogno d'altro, signore?"))

    def test_site_typo_resolves_to_configured_domain_without_keyboard_typing(self):
        with temporary_project() as directory:
            root = Path(directory)
            populate(root)
            (root / "config/websites.json").write_text(json.dumps({"chatgpt": {
                "label": "ChatGPT", "url": "https://chatgpt.com/", "aliases": ["chatgbt.com", "chat gpt punto com"]}}), encoding="utf-8")
            tool = OpenResourceTool(WebsiteCatalog(root))
            for target in ("chatgbt.com", "ChatGPT", "chat gpt punto com", "https://chatgbt.com"):
                with self.subTest(target=target):
                    arguments = tool.validate({"target": target})
                    self.assertEqual(arguments["target"], "https://chatgpt.com/")
                    with patch("os.startfile") as opened:
                        tool.execute(arguments, TaskContext("url", threading.Event(), 5))
                    opened.assert_called_once_with("https://chatgpt.com/")

    def test_unknown_spoken_domain_needs_exact_confirmation_but_typed_domain_does_not(self):
        with temporary_project() as directory:
            root = Path(directory)
            populate(root)
            tool = OpenResourceTool(WebsiteCatalog(root))
            registry = ToolRegistry(SecurityPolicy(ApprovalStore()))
            registry.register(tool)
            call = ToolCall(tool.name, '{"target":"https://example.org/"}')
            with patch("os.startfile") as opened:
                with self.assertRaises(UserError):
                    registry.execute(call, TaskContext("voice", threading.Event(), 5, origin="voice"), lambda *_: None)
                opened.assert_not_called()
                registry.execute(call, TaskContext("chat", threading.Event(), 5, origin="chat"), lambda *_: self.fail("Typed URL must not prompt"))
                opened.assert_called_once_with("https://example.org/")

    def test_website_selector_produces_registered_url_tool_instead_of_gui_typing(self):
        provider = OllamaProvider(OllamaSettings(enabled=True))
        selection = {"request_type": "open_resource", "target": "chatgbt.com", "application": "", "operations": [], "query": "", "limit": 20}
        schemas = [{"name": "open_resource", "description": "Siti"}, {"name": "get_current_datetime", "description": "Clock"}]
        with patch.object(provider, "_json", return_value={"message": {"content": json.dumps(selection)}}):
            calls = provider.select_initial_tools([{"role": "user", "content": "chatgbt.com"}], schemas, TaskContext("select", threading.Event(), 5))
        self.assertEqual([call.name for call in calls], ["open_resource"])
        self.assertEqual(json.loads(calls[0].arguments_json), {"target": "chatgbt.com"})
