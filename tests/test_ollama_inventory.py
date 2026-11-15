"""Read-only inventory must preserve uncertainty, cancellation and one adapter."""

from contextlib import contextmanager
import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

from jarvis.brain.ollama import OllamaProvider
from jarvis.brain.ollama_inventory import (same_model, native_context_length, runtime_facts,
    inventory_summary, describe_inventory, positive_integer)
from jarvis.core.models import Cancelled, TaskTimeout, UserError
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import OllamaSettings


TAGS = {"models": [{"name": "qwen3.5:9b"}]}
SHOW = {"capabilities": ["completion", "tools", "vision"], "model_info": {
    "general.architecture": "qwen35", "qwen35.context_length": 262144}}
RUNNING = {"models": [{"name": "qwen3.5:9b", "size": 1000, "size_vram": 1000, "context_length": 16384}]}


class InventoryTests(unittest.TestCase):
    def provider(self):
        return OllamaProvider(OllamaSettings(enabled=True))

    def context(self):
        return TaskContext("inventory-test", threading.Event(), 5)

    def test_model_alias_comparison_does_not_confuse_distinct_quantities(self):
        self.assertTrue(same_model(" qwen3.5 ", "qwen3.5:latest"))
        self.assertFalse(same_model("qwen3.5:9b", "qwen3.5:4b"))
        self.assertFalse(same_model("", "qwen3.5"))
        self.assertFalse(same_model(True, "qwen3.5"))

    def test_native_context_prefers_declared_architecture_and_rejects_fake_numbers(self):
        self.assertEqual(native_context_length({"other.context_length": 8192, "general.architecture": "qwen35", "qwen35.context_length": 262144}), 262144)
        for value in (True, False, float("inf"), float("nan"), -3, "16384", 1.5, 10**400):
            with self.subTest(value=repr(value)):
                self.assertIsNone(native_context_length({"model.context_length": value}))

    def test_missing_vram_is_unknown_while_reported_zero_is_cpu(self):
        unknown = runtime_facts({"models": [{"name": "qwen3.5:9b", "size": 1000}]}, "qwen3.5:9b")
        self.assertTrue(unknown["loaded"])
        self.assertIsNone(unknown["size_vram_bytes"])
        self.assertEqual(unknown["residency"], "unknown")
        cpu = runtime_facts({"models": [{"name": "qwen3.5:9b", "size": 1000, "size_vram": 0}]}, "qwen3.5:9b")
        self.assertEqual(cpu["residency"], "cpu")

    def test_unloaded_and_uninspectable_runtime_are_distinct(self):
        self.assertFalse(runtime_facts({"models": []}, "qwen3.5:9b")["loaded"])
        self.assertIsNone(runtime_facts({"models": [{}]}, "qwen3.5:9b")["loaded"])
        self.assertIsNone(runtime_facts({"models": [{"name": ""}]}, "qwen3.5:9b")["loaded"])
        with self.assertRaises(ValueError):
            runtime_facts({"models": "broken"}, "qwen3.5:9b")

    def test_inventory_only_reads_tags_show_and_ps_through_existing_adapter(self):
        provider = self.provider()
        with patch.object(provider, "_json", side_effect=[TAGS, SHOW, RUNNING]) as request:
            status = provider.inventory(self.context())
        self.assertEqual([(row.args[0], row.args[1]) for row in request.call_args_list],
                         [("GET", "/api/tags"), ("POST", "/api/show"), ("GET", "/api/ps")])
        self.assertEqual(request.call_args_list[1].args[2], {"model": "qwen3.5:9b"})
        value = status["local_inventory"]
        self.assertEqual(value["native_context_length"], 262144)
        self.assertEqual(value["runtime_context_length"], 16384)
        self.assertEqual(value["configured_context_length"], 16384)
        self.assertEqual(value["residency"], "gpu")

    def test_ordinary_model_check_does_not_add_runtime_scans(self):
        provider = self.provider()
        with patch.object(provider, "_json", side_effect=[TAGS, SHOW]) as request:
            provider.check(self.context())
        self.assertEqual(request.call_count, 2)
        self.assertNotIn("/api/ps", str(request.call_args_list))

    def test_failed_runtime_probe_keeps_installation_facts_without_claiming_unload(self):
        provider = self.provider()
        with patch.object(provider, "_json", side_effect=[TAGS, SHOW, UserError("fixture unavailable")]):
            result = provider.inventory(self.context())["local_inventory"]
        self.assertIsNone(result["loaded"])
        self.assertFalse(result["runtime_probe_available"])
        self.assertEqual(result["installed_models"], ["qwen3.5:9b"])
        self.assertIn("non verificato", describe_inventory(result))

    def test_malformed_runtime_does_not_blank_healthy_model_metadata(self):
        provider = self.provider()
        with patch.object(provider, "_json", side_effect=[TAGS, SHOW, {"models": None}]):
            value = provider.inventory(self.context())["local_inventory"]
        self.assertFalse(value["runtime_probe_available"])
        self.assertEqual(value["native_context_length"], 262144)

    def test_user_stop_is_not_swallowed_as_a_partial_inventory(self):
        provider = self.provider()
        with patch.object(provider, "_json", side_effect=[TAGS, SHOW, Cancelled("stop")]), self.assertRaises(Cancelled):
            provider.inventory(self.context())

    def test_optional_runtime_timeout_does_not_fail_the_parent_model_check(self):
        provider = self.provider()
        with patch.object(provider, "_json", side_effect=[TAGS, SHOW, TaskTimeout("runtime timeout")]):
            value = provider.inventory(self.context())["local_inventory"]
        self.assertIsNone(value["loaded"])
        self.assertEqual(value["runtime_error"], "runtime timeout")

    def test_invalid_model_inventory_never_loads_or_downloads_another_model(self):
        provider = self.provider()
        for payload in ({"models": None}, {"models": [True]}, {"models": []}):
            with self.subTest(payload=payload), patch.object(provider, "_json", return_value=payload) as request:
                with self.assertRaises(UserError):
                    provider.inventory(self.context())
                self.assertEqual(request.call_count, 1)

    def test_declared_vision_capability_is_not_presented_as_an_enabled_tool(self):
        status = inventory_summary({"model": "qwen3.5:9b", "capabilities": ["vision"]}, RUNNING)
        self.assertIn("non abilitano nuovi strumenti", describe_inventory(status))


class InventoryUiTests(unittest.TestCase):
    def test_panel_updates_on_worker_without_creating_personal_tasks_or_operations(self):
        from PySide6.QtWidgets import QApplication
        from jarvis.ui.main_window import MainWindow
        from jarvis.ui.presenter import Presenter
        from tests.support import make_controller, temporary_project
        app = QApplication.instance() or QApplication([])
        with temporary_project() as temporary:
            controller = make_controller(Path(temporary))
            window = MainWindow()
            presenter = Presenter(window, controller)
            provider = self.provider_status()
            threads = []

            def inspect(_context):
                threads.append(threading.get_ident())
                return provider

            with patch.object(OllamaProvider, "inventory", side_effect=inspect):
                window.model_button.click()
                deadline = time.monotonic() + 3
                while presenter.worker is not None and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(.005)
                self.assertIsNone(presenter.worker)
                self.assertIn("262144", presenter.model_status_dialog.details.toPlainText())
                self.assertNotEqual(threads[0], threading.get_ident())
                self.assertEqual(controller.repository.tasks(), [])
                self.assertEqual(controller.repository.operations(), [])
            presenter.close()
            window.deleteLater()
            app.processEvents()

    def provider_status(self):
        return {"model": "qwen3.5:9b", "capabilities": ["tools"], "local_inventory": inventory_summary(
            {"model": "qwen3.5:9b", "native_context_length": 262144}, RUNNING)}
