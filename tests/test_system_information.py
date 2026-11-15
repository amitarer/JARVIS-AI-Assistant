"""Read-only system tool contracts, native invariants and audited LLM dispatch."""

from datetime import datetime, timedelta, timezone
from dataclasses import replace
import json
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

from jarvis.bootstrap import build_tool_registry
from jarvis.brain.ollama import OllamaProvider
from jarvis.core.models import Cancelled, TaskTimeout, ToolCall, UserError
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import load_settings, OllamaSettings
from jarvis.infrastructure.system_information import SystemInformation, PowerStatus
from jarvis.memory.database import Database
from jarvis.memory.repository import Repository
from jarvis.security.approvals import ApprovalStore
from jarvis.security.policy import SecurityPolicy
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.system_information import OPERATIONS, SystemInformationTool
from tests.support import populate, temporary_project


class SystemInformationTests(unittest.TestCase):
    def setUp(self):
        self.service = SystemInformation()
        self.context = TaskContext("system-info-test", threading.Event(), 20)

    def registry(self, name):
        registry = ToolRegistry(SecurityPolicy(ApprovalStore()))
        registry.register(SystemInformationTool(self.service, name))
        return registry

    @unittest.skipUnless(os.name == "nt", "Requires native Windows")
    def test_datetime_comes_from_live_windows_clock_and_has_correct_local_date(self):
        before = datetime.now(timezone.utc)
        result = self.service.get_current_datetime(self.context)
        after = datetime.now(timezone.utc)
        observed = datetime.fromisoformat(result["observed_at_utc"])
        # Python 3.12 and the precise Win32 clock can have different resolutions.
        tolerance = timedelta(milliseconds=50)
        self.assertLessEqual(before - tolerance, observed)
        self.assertLessEqual(observed, after + tolerance)
        local = observed.astimezone()
        self.assertEqual(result["date"], local.date().isoformat())
        self.assertEqual(result["time"], local.strftime("%H:%M:%S"))
        self.assertEqual(result["timezone"]["utc_offset_seconds"], int(local.utcoffset().total_seconds()))
        self.assertTrue(result["timezone"]["windows_id"])

    def test_date_format_is_italian_independent_of_process_locale(self):
        service_time = datetime(2026, 11, 14, 12, 30, tzinfo=timezone.utc)
        with patch.object(self.service, "_utc_now", return_value=service_time), patch.object(self.service, "_timezone_id", return_value="test-zone"):
            result = self.service.get_current_datetime(self.context)
        local = service_time.astimezone()
        self.assertEqual(result["weekday_it"], ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")[local.weekday()])
        self.assertIn("novembre", result["date_it"])
        self.assertEqual(result["time_it"], local.strftime("%H:%M"))

    @unittest.skipUnless(os.name == "nt", "Requires native Windows")
    def test_live_memory_is_consistent_and_available_is_not_total(self):
        result = self.service.get_memory_information(self.context)
        self.assertGreater(result["total_bytes"], 0)
        self.assertLessEqual(0, result["available_bytes"])
        self.assertLessEqual(result["available_bytes"], result["total_bytes"])
        self.assertEqual(result["used_bytes"] + result["available_bytes"], result["total_bytes"])
        self.assertLessEqual(0, result["used_percent"])
        self.assertLessEqual(result["used_percent"], 100)

    @unittest.skipUnless(os.name == "nt", "Requires native Windows")
    def test_live_disk_contains_system_drive_and_valid_free_space(self):
        result = self.service.get_disk_information(self.context)
        root = Path(os.environ["SystemRoot"]).anchor.casefold()
        disk = next(item for item in result["disks"] if item["path"].casefold() == root)
        self.assertTrue(disk["available"])
        self.assertGreater(disk["total_bytes"], 0)
        self.assertLessEqual(0, disk["free_bytes"])
        self.assertLessEqual(disk["free_bytes"], disk["total_bytes"])
        self.assertEqual(disk["used_bytes"] + disk["free_bytes"], disk["total_bytes"])

    def test_battery_absence_and_unknown_status_are_not_reported_as_empty(self):
        fake_kernel = Mock()
        self.service._kernel32 = fake_kernel
        def write_status(pointer):
            status = pointer._obj
            status.flags, status.percent, status.ac, status.remaining = 128, 255, 1, 0xFFFFFFFF
            return True
        fake_kernel.GetSystemPowerStatus.side_effect = write_status
        with patch.object(self.service, "_stamp", return_value={}):
            result = self.service.get_battery_status(self.context)
        self.assertIs(result["present"], False)
        self.assertIsNone(result["percent"])
        self.assertIsNone(result["remaining_seconds"])

    def test_unavailable_cpu_counter_is_null_instead_of_zero(self):
        with patch.object(self.service, "_cpu_times", return_value=(0, 0)):
            result = self.service._cpu_usage(self.context)
        self.assertIsNone(result["percent"])

    def test_process_query_is_payload_data_and_never_interpolated_into_script(self):
        query = "python'; Write-Output SHOULD_NOT_RUN; #"
        response = {"processes": [], "returned": 0}
        with patch("jarvis.infrastructure.system_information.powershell", return_value=(0, json.dumps(response))) as native, \
                patch.object(self.service, "_stamp", return_value={}):
            self.service.get_process_information(self.context, query=query, limit=2)
        self.assertNotIn(query, native.call_args.args[0])
        self.assertEqual(native.call_args.kwargs["payload"], {"section": "processes", "query": query, "limit": 2})

    def test_invalid_cim_response_is_reported_without_fabricated_data(self):
        for code, output in ((1, "private native error"), (0, "not json"), (0, "[]")):
            with self.subTest(code=code, output=output), \
                    patch("jarvis.infrastructure.system_information.powershell", return_value=(code, output)), \
                    self.assertRaises(UserError) as caught:
                self.service.get_system_information(self.context)
            self.assertNotIn("private native error", str(caught.exception))

    def test_current_time_tool_has_no_side_effect_or_confirmation(self):
        registry = self.registry("get_current_datetime")
        with patch.object(self.service, "get_current_datetime", return_value={
                "source": "clock", "observed_at_utc": "2026-11-14T12:00:00+00:00", "time_it": "13:00",
                "weekday_it": "sabato", "date_it": "14 novembre 2026"}):
            result = registry.execute(ToolCall("get_current_datetime", "{}"), self.context,
                                      lambda *_: self.fail("Read-only time must not require confirmation"))
        self.assertTrue(result.observation)
        self.assertTrue(result.evidence["read_only"])
        self.assertEqual(json.loads(result.message)["time_it"], "13:00")

    def test_extra_parameters_invalid_limits_and_unknown_tools_are_denied(self):
        registry = self.registry("get_process_information")
        for parameters in ({"limit": True}, {"limit": 51}, {"limit": 0}, {"query": []}, {"command": "Get-Date"}):
            with self.subTest(parameters=parameters), self.assertRaises(UserError):
                registry.execute(ToolCall("get_process_information", json.dumps(parameters)), self.context, lambda *_: None)
        clock = self.registry("get_current_datetime")
        with self.assertRaises(UserError):
            clock.execute(ToolCall("get_current_datetime", '{"command":"Get-Date"}'), self.context, lambda *_: None)
        with self.assertRaises(ValueError):
            SystemInformationTool(self.service, "arbitrary_method")

    def test_cancelled_or_expired_request_does_not_call_windows(self):
        registry = self.registry("get_hardware_information")
        self.context.cancellation.set()
        with patch.object(self.service, "get_hardware_information") as native, self.assertRaises(Cancelled):
            registry.execute(ToolCall("get_hardware_information", "{}"), self.context, lambda *_: None)
        native.assert_not_called()
        expired = TaskContext("expired", threading.Event(), -1)
        with patch.object(self.service, "get_hardware_information") as native, self.assertRaises(TaskTimeout):
            registry.execute(ToolCall("get_hardware_information", "{}"), expired, lambda *_: None)
        native.assert_not_called()

    def test_system_tool_limits_its_own_deadline(self):
        registry = self.registry("get_memory_information")
        parent = TaskContext("long-task", threading.Event(), 180)
        def read(context):
            self.assertLessEqual(context.remaining, 20)
            self.assertIs(context.cancellation, parent.cancellation)
            self.assertEqual(context.task_id, parent.task_id)
            return {"source": "memory", "observed_at_utc": "2026-11-14T12:00:00+00:00",
                    "total_gib": 32, "available_gib": 16, "used_percent": 50}
        with patch.object(self.service, "get_memory_information", side_effect=read):
            registry.execute(ToolCall("get_memory_information", "{}"), parent, lambda *_: None)


class SystemInformationIntegrationTests(unittest.TestCase):
    def test_invalid_structured_selector_cannot_request_arbitrary_tools(self):
        provider = OllamaProvider(OllamaSettings(enabled=True))
        schemas = [{"name": "get_current_datetime", "description": "Clock"}]
        selections = [
            {"operations": ["run_powershell"], "query": "", "limit": 20},
            {"operations": ["get_current_datetime", "get_current_datetime"], "query": "", "limit": 20},
            {"operations": ["get_current_datetime"], "query": "", "limit": True},
            {"operations": "get_current_datetime", "query": "", "limit": 20},
            {"operations": [], "query": "", "limit": 20, "command": "Get-Date"},
        ]
        for selection in selections:
            selection = {"request_type": "system_information", "application": "", "target": "", **selection}
            with self.subTest(selection=selection), patch.object(provider, "_json", return_value={
                    "message": {"content": json.dumps(selection)}}), self.assertRaises(UserError):
                provider.select_initial_tools([{"role": "user", "content": "Che ore sono?"}], schemas,
                                             TaskContext("selector", threading.Event(), 5))

    def test_selector_uses_only_registered_read_only_schema_and_data_parameters(self):
        provider = OllamaProvider(OllamaSettings(enabled=True))
        schemas = [{"name": "get_process_information", "description": "Processi utente"}]
        query = "python'; Write-Output ignored"
        with patch.object(provider, "_json", return_value={"message": {"content": json.dumps({
                "request_type": "system_information", "application": "", "target": "", "operations": ["get_process_information"], "query": query, "limit": 3})}}) as call:
            selections = provider.select_initial_tools([{"role": "user", "content": "Leggi i processi"}], schemas,
                                                       TaskContext("selector", threading.Event(), 5))
        self.assertEqual(selections[0].name, "get_process_information")
        self.assertEqual(json.loads(selections[0].arguments_json), {"query": query, "limit": 3})
        request = call.call_args.args[2]
        self.assertIs(request["think"], False)
        self.assertEqual(request["format"]["properties"]["operations"]["items"]["enum"], ["get_process_information"])

    def test_action_ignores_stale_history_and_does_not_execute_suggested_readings(self):
        provider = OllamaProvider(OllamaSettings(enabled=True))
        messages = [{"role": "user", "content": "Che ore sono?"},
                    {"role": "assistant", "content": "Sono le 12:00. Le finestre aperte sono..."},
                    {"role": "user", "content": "Aprimi Chrome"}]
        selection = {"request_type": "other", "application": "", "target": "", "operations": ["get_current_datetime"], "query": "", "limit": 20}
        with patch.object(provider, "_json", return_value={"message": {"content": json.dumps(selection)}}) as api:
            calls = provider.select_initial_tools(messages, [{"name": "get_current_datetime", "description": "Clock"}],
                                                TaskContext("route", threading.Event(), 10))
        self.assertEqual(calls, [])
        self.assertEqual(api.call_args.args[2]["messages"][1:], [{"role": "user", "content": "Aprimi Chrome"}])

    def test_open_command_reaches_application_tool_after_system_information_turn(self):
        from jarvis.core.controller import Controller
        from jarvis.core.models import ToolResult
        with temporary_project() as directory:
            root = Path(directory)
            populate(root)
            database = Database(root / "data/test.sqlite3")
            database.initialize()
            repository = Repository(database)
            settings = replace(load_settings(root), ollama=OllamaSettings(enabled=True))
            controller = Controller(settings, repository, build_tool_registry(settings, repository))
            repository.add_message("user", "Che ore sono? Quali finestre sono aperte?")
            repository.add_message("assistant", "Sono le 12:00. Finestre aperte: Chrome.")
            selection = {"request_type": "open_application", "application": "chrome", "target": "", "operations": ["get_current_datetime", "get_open_applications"], "query": "", "limit": 20}
            with patch.object(OllamaProvider, "check", return_value={}), \
                    patch.object(OllamaProvider, "_json", return_value={"message": {"content": json.dumps(selection)}}), \
                    patch.object(OllamaProvider, "chat") as draft, \
                    patch.object(controller.tools._tools["open_application"], "execute", return_value=ToolResult("Avvio Chrome accettato.", {"process_created": True})) as opened, \
                    patch.object(SystemInformation, "get_current_datetime") as clock:
                events = []
                controller.run({"kind": "chat", "text": "Aprimi Chrome"}, threading.Event(), events.append, lambda *_: None)
            opened.assert_called_once()
            draft.assert_not_called()
            clock.assert_not_called()
            self.assertEqual([operation["tool"] for operation in repository.operations()], ["open_application"])
            self.assertEqual(next(event.data for event in events if event.kind == "response"), "Avvio Chrome accettato.")

    def test_production_registry_exposes_system_tools_and_denies_generated_shell(self):
        with temporary_project() as directory:
            root = Path(directory)
            populate(root)
            database = Database(root / "data/test.sqlite3")
            database.initialize()
            registry = build_tool_registry(load_settings(root), Repository(database))
            names = {schema["name"] for schema in registry.schemas(for_model=True)}
            self.assertTrue(set(OPERATIONS) <= names)
            self.assertNotIn("run_powershell", names)
            with self.assertRaises(UserError):
                registry.execute(ToolCall("run_powershell", '{"command":"Write-Output test"}'),
                                 TaskContext("test", threading.Event(), 5), lambda *_: None)

    def test_clock_observation_is_audited_in_isolated_sqlite(self):
        from jarvis.core.controller import Controller
        with temporary_project() as directory:
            root = Path(directory)
            populate(root)
            database = Database(root / "data/test.sqlite3")
            database.initialize()
            repository = Repository(database)
            controller = Controller(load_settings(root), repository, build_tool_registry(load_settings(root), repository))
            repository.create_task("clock-test", "chat", "Che ore sono?")
            context = TaskContext("clock-test", threading.Event(), 5)
            with patch.object(SystemInformation, "get_current_datetime", return_value={
                    "source": "Windows clock", "observed_at_utc": "2026-11-14T12:00:00+00:00", "time_it": "13:00",
                    "weekday_it": "sabato", "date_it": "14 novembre 2026"}):
                controller.execute_tool(ToolCall("get_current_datetime", "{}"), context, lambda *_: None, lambda *_: None)
            operation = repository.operations()[0]
            self.assertEqual(operation["status"], "succeeded")
            self.assertEqual(operation["tool"], "get_current_datetime")
            self.assertEqual(json.loads(operation["evidence_json"])["source"], "Windows clock")
            self.assertTrue(json.loads(operation["evidence_json"])["read_only"])

    def test_two_turns_read_fresh_clock_and_never_generate_an_unverified_answer(self):
        from jarvis.core.controller import Controller
        with temporary_project() as directory:
            root = Path(directory)
            populate(root)
            database = Database(root / "data/test.sqlite3")
            database.initialize()
            repository = Repository(database)
            settings = replace(load_settings(root), ollama=OllamaSettings(enabled=True))
            controller = Controller(settings, repository, build_tool_registry(settings, repository))
            snapshots = [{"source": "clock", "observed_at_utc": f"2026-11-14T12:0{index}:00+00:00",
                          "time_it": f"13:0{index}", "weekday_it": "sabato", "date_it": "14 novembre 2026"}
                         for index in range(2)]
            with patch.object(OllamaProvider, "check", return_value={}), \
                    patch.object(OllamaProvider, "select_initial_tools", return_value=[ToolCall("get_current_datetime", "{}")]), \
                    patch.object(OllamaProvider, "chat") as draft, \
                    patch.object(SystemInformation, "get_current_datetime", side_effect=snapshots) as clock:
                for index in range(2):
                    events = []
                    controller.run({"kind": "chat", "text": "Che ore sono?"}, threading.Event(), events.append, lambda *_: None)
                    response = next(event.data for event in events if event.kind == "response")
                    self.assertIn(f"13:0{index}", response)
            self.assertEqual(clock.call_count, 2)
            draft.assert_not_called()
            self.assertEqual(len(repository.operations()), 2)

    def test_non_system_conversation_keeps_existing_chat_path(self):
        from jarvis.core.controller import Controller
        with temporary_project() as directory:
            root = Path(directory)
            populate(root)
            database = Database(root / "data/test.sqlite3")
            database.initialize()
            repository = Repository(database)
            settings = replace(load_settings(root), ollama=OllamaSettings(enabled=True))
            controller = Controller(settings, repository, build_tool_registry(settings, repository))
            with patch.object(OllamaProvider, "check", return_value={}), \
                    patch.object(OllamaProvider, "select_initial_tools", return_value=[]), \
                    patch.object(OllamaProvider, "chat", return_value=("Ciao!", [], {})):
                events = []
                controller.run({"kind": "chat", "text": "Ciao"}, threading.Event(), events.append, lambda *_: None)
            self.assertEqual(next(event.data for event in events if event.kind == "response"), "Ciao!")
            self.assertEqual(repository.operations(), [])
