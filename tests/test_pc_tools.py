"""PC tool boundaries: discovery, exact approvals, cancellation and observations."""

from dataclasses import replace
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from jarvis.core.models import Cancelled, Risk, ToolCall, ToolResult, UserError
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import OllamaSettings
from jarvis.security.approvals import ApprovalStore
from jarvis.security.policy import SecurityPolicy
from jarvis.tools.applications import ApplicationCatalog, ListApplicationsTool
from jarvis.tools.desktop import DesktopSession, DesktopActionTool, InspectDesktopTool
from jarvis.tools.open_application import OpenApplicationTool
from jarvis.tools.pc import InspectFilesTool, OpenResourceTool, RunPowerShellTool
from jarvis.tools.registry import ToolRegistry
from tests.support import make_controller, populate, temporary_project


class PcToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = temporary_project()
        self.root = Path(self.temp.name)
        populate(self.root)
        self.context = TaskContext("pc-test", threading.Event(), 15)

    def tearDown(self):
        self.temp.cleanup()

    def registry(self, tool):
        registry = ToolRegistry(SecurityPolicy(ApprovalStore()))
        registry.register(tool)
        return registry

    def test_installed_app_is_discovered_without_a_configured_entry(self):
        rows = [{"Name": "Calcolatrice", "AppID": "Microsoft.Calculator!App"}]
        with patch("jarvis.tools.applications.powershell", return_value=(0, json.dumps(rows))):
            catalog = ApplicationCatalog(self.root)
            application = catalog.resolve("calcolatrice", self.context)
            self.assertEqual(application.app_id, rows[0]["AppID"])
            tool = OpenApplicationTool({}, catalog)
            arguments = tool.validate({"application_id": "Calcolatrice"})
            with patch("os.startfile") as launch:
                result = tool.execute(arguments, self.context)
            launch.assert_called_once_with("shell:AppsFolder\\Microsoft.Calculator!App")
            self.assertTrue(result.evidence["launch_accepted"])
            self.assertFalse(result.evidence["window_verified"])

    def test_configured_apps_reload_without_restarting(self):
        with patch("jarvis.tools.applications.powershell", return_value=(0, "[]")):
            catalog = ApplicationCatalog(self.root)
            self.assertEqual(len(catalog.applications(self.context)), 1)
            path = self.root / "config/applications.json"
            rows = json.loads(path.read_text())
            rows["chrome"] = {"label": "Google Chrome", "executable": r"C:\Apps\chrome.exe"}
            path.write_text(json.dumps(rows))
            self.assertEqual(catalog.resolve("chrome", self.context).label, "Google Chrome")

    def test_ambiguous_app_name_is_not_silently_launched(self):
        rows = [{"Name": "Studio One", "AppID": "One"}, {"Name": "Studio Two", "AppID": "Two"}]
        with patch("jarvis.tools.applications.powershell", return_value=(0, json.dumps(rows))):
            with self.assertRaisesRegex(UserError, "ambiguo"):
                ApplicationCatalog(self.root).resolve("studio", self.context)

    def test_voice_aliases_resolve_to_configured_application_without_fuzzy_guessing(self):
        path = self.root / "config/applications.json"
        rows = json.loads(path.read_text())
        rows["chrome"] = {"label": "Google Chrome", "executable": r"C:\Apps\chrome.exe", "aliases": ["microm", "crome"]}
        path.write_text(json.dumps(rows), encoding="utf-8")
        with patch("jarvis.tools.applications.powershell", return_value=(0, "[]")):
            catalog = ApplicationCatalog(self.root)
            self.assertEqual(catalog.resolve("Microm", self.context).identifier, "chrome")
            with self.assertRaises(UserError):
                catalog.resolve("unrelated_program", self.context)

    def test_real_application_name_takes_precedence_over_an_alias(self):
        path = self.root / "config/applications.json"
        rows = json.loads(path.read_text())
        rows["chrome"] = {"label": "Google Chrome", "executable": r"C:\Apps\chrome.exe", "aliases": ["microm"]}
        path.write_text(json.dumps(rows), encoding="utf-8")
        with patch("jarvis.tools.applications.powershell", return_value=(0, '[{"Name":"Microm","AppID":"actual-app"}]')):
            self.assertEqual(ApplicationCatalog(self.root).resolve("Microm", self.context).app_id, "actual-app")

    def test_desktop_actions_cannot_accept_extra_payload_or_unobserved_shapes(self):
        tool = DesktopActionTool()
        invalid = [{"action": "type_text", "window_id": 1, "text": "hello", "keys": "ENTER"},
                   {"action": "click", "window_id": True, "x": 1, "y": 2},
                   {"action": "press_keys", "window_id": 1, "keys": "CTRL+L;cmd"},
                   {"action": "click", "window_id": 1, "control_id": "42.1", "x": 0, "y": 0}]
        for arguments in invalid:
            with self.subTest(arguments=arguments), self.assertRaises(UserError):
                tool.validate(arguments)

    def test_read_and_focus_do_not_prompt_but_typing_requires_exact_approval(self):
        tool = DesktopActionTool()
        registry = self.registry(tool)
        with patch("jarvis.tools.desktop.desktop_request", return_value={"message": "ok"}) as native:
            registry.execute(ToolCall(tool.name, '{"action":"focus","window_id":12}'), self.context,
                             lambda *_: self.fail("Focus must not ask for approval"))
            native.reset_mock()
            with self.assertRaises(UserError):
                registry.execute(ToolCall(tool.name, '{"action":"type_text","window_id":12,"text":"hello"}'), self.context, lambda *_: None)
            native.assert_not_called()

    def test_shell_never_runs_without_concrete_approval(self):
        tool = RunPowerShellTool(self.root)
        registry = self.registry(tool)
        call = ToolCall(tool.name, '{"command":"Write-Output test"}')
        with patch("jarvis.tools.pc.powershell") as native:
            with self.assertRaises(UserError):
                registry.execute(call, self.context, lambda *_: None)
            native.assert_not_called()

    def test_shell_grant_is_bound_to_exact_command_and_working_directory(self):
        tool = RunPowerShellTool(self.root)
        registry = self.registry(tool)
        call = ToolCall(tool.name, '{"command":"Write-Output test"}')
        def approve(request, context):
            self.assertEqual(request.risk, Risk.HIGH)
            self.assertEqual(json.loads(request.call.arguments_json), {"command": "Write-Output test", "working_directory": str(self.root)})
            return registry.policy.approvals.issue(request)
        with patch("jarvis.tools.pc.powershell", return_value=(0, "test")) as native:
            result = registry.execute(call, self.context, approve)
        native.assert_called_once()
        self.assertTrue(result.evidence["command_succeeded"])

    def test_stop_after_shell_confirmation_prevents_execution(self):
        tool = RunPowerShellTool(self.root)
        registry = self.registry(tool)
        def approve(request, context):
            token = registry.policy.approvals.issue(request)
            context.cancellation.set()
            return token
        with patch("jarvis.tools.pc.powershell") as native, self.assertRaises(Cancelled):
            registry.execute(ToolCall(tool.name, '{"command":"Write-Output test"}'), self.context, approve)
        native.assert_not_called()

    def test_file_preview_is_bounded_and_binary_is_rejected(self):
        path = self.root / "preview.txt"
        path.write_text("è" * 7000, encoding="utf-8")
        tool = InspectFilesTool()
        result = tool.execute(tool.validate({"action": "read_text", "path": str(path)}), self.context)
        self.assertTrue(json.loads(result.message)["truncated"])
        self.assertTrue(result.observation)
        path.write_bytes(b"\x00\x01")
        with self.assertRaises(UserError):
            tool.execute(tool.validate({"action": "read_text", "path": str(path)}), self.context)

    def test_resource_opener_rejects_scripts_credentials_and_relative_paths(self):
        tool = OpenResourceTool()
        path = self.root / "script.ps1"
        path.write_text("Write-Output test")
        for target in (str(path), "https://user:secret@example.com", "relative.txt", "javascript:alert(1)"):
            with self.subTest(target=target), self.assertRaises(UserError):
                tool.validate({"target": target})

    def test_desktop_inspection_rejects_invalid_handles(self):
        for handle in (True, -1, "123", 2**64):
            with self.subTest(handle=handle), self.assertRaises(UserError):
                InspectDesktopTool().validate({"window_id": handle})

    def test_desktop_session_rejects_guessed_coordinates_and_another_task(self):
        session = DesktopSession()
        session.observe({"window": {"window_id": 12, "process_id": 44, "title": "Test"},
                         "controls": [{"control_id": "42.1", "x": 10, "y": 20}]}, self.context)
        with self.assertRaisesRegex(UserError, "non rilevati"):
            session.target({"action": "click", "window_id": 12, "x": 11, "y": 20}, self.context)
        with self.assertRaisesRegex(UserError, "questa richiesta"):
            session.target({"action": "focus", "window_id": 12}, TaskContext("other", threading.Event(), 5))

    def test_desktop_session_binds_input_to_observed_owner_process(self):
        session = DesktopSession()
        session.observe({"window": {"window_id": 12, "process_id": 44, "title": "Test"},
                         "controls": [{"control_id": "42.1", "x": 10, "y": 20}]}, self.context)
        tool = DesktopActionTool(session)
        with patch("jarvis.tools.desktop.desktop_request", return_value={"message": "ok"}) as native:
            tool.execute(tool.validate({"action": "click", "window_id": 12, "control_id": "42.1"}), self.context)
        self.assertEqual(native.call_args.args[0]["expected_process_id"], 44)

    def test_observation_allows_model_to_answer_instead_of_replaying_raw_json(self):
        from jarvis.brain.ollama import OllamaProvider
        controller_root = self.root / "controller"
        controller_root.mkdir()
        controller = make_controller(controller_root)
        controller.settings = replace(controller.settings, ollama=OllamaSettings(enabled=True))
        tool = InspectFilesTool()
        controller.tools.register(tool)
        call = ToolCall(tool.name, json.dumps({"action": "list", "path": str(self.root)}))
        with patch.object(OllamaProvider, "check", return_value={}), \
                patch.object(OllamaProvider, "chat", side_effect=[("", [call], {}), ("La cartella contiene config.", [], {})]):
            events = []
            controller.run({"kind": "chat", "text": "Cosa contiene la cartella?"}, threading.Event(), events.append, lambda *_: None)
        self.assertEqual(next(event.data for event in events if event.kind == "response"), "La cartella contiene config.")
