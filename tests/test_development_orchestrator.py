"""Development-agent authorization and isolation checks, without starting an AI."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from development.bootstrap_tools import extract_checked
from development.orchestrator.codex_worker import validate_response
from development.orchestrator.fixture import validate_relative_path
from development.orchestrator.permissions import clean_environment
from development.orchestrator.runner import DevelopmentRunner, REVIEW_SCHEMA, TEST_SCHEMA
from development.ruflo_mcp_server import permitted
from development.orchestrator.mcp_client import decode_tool_result


class DevelopmentSafetyTests(unittest.TestCase):
    def test_archive_traversal_cannot_write_outside_installation(self):
        base = Path(__file__).resolve().parents[1] / "data/test-runs"
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as temporary:
            folder = Path(temporary)
            archive = folder / "unsafe.zip"
            with ZipFile(archive, "w") as zipped:
                zipped.writestr("../escaped.txt", "synthetic")
            with self.assertRaises(ValueError):
                extract_checked(archive, folder / "installation")
            self.assertFalse((folder / "escaped.txt").exists())

    def test_task_paths_cannot_target_metadata_or_escape_worktree(self):
        for value in ("../data", "fixture/../../.env", "C:/Windows/test", "/root/file", "fixture\\test", ".git/config", ".codex/config.toml", ".env"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_relative_path(value)
        self.assertEqual(str(validate_relative_path("fixture/normalize.py")), "fixture/normalize.py")

    def test_model_output_cannot_smuggle_extra_authorization_or_fake_boolean(self):
        valid = {"summary": "observed", "tests_ran": True, "observed_result": "two tests passed", "remaining_issues": []}
        validate_response(valid, TEST_SCHEMA)
        for invalid in ({**valid, "allow_merge": True}, {**valid, "tests_ran": "true"},
                        {**valid, "remaining_issues": [123]}, {"summary": "missing required receipts"}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_response(invalid, TEST_SCHEMA)
        with self.assertRaises(ValueError):
            validate_response({"verdict": "merge_now", "summary": "invalid", "findings": []}, REVIEW_SCHEMA)

    def test_unapproved_or_completed_backlog_never_dispatches(self):
        base = Path(__file__).resolve().parents[1] / "data/test-runs"
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as temporary, patch("development.orchestrator.runner.STATE", Path(temporary)):
            runner = object.__new__(DevelopmentRunner)
            runner.config = {"authorization": {"approved_task_ids": ["DEV-SMOKE-001"]}}
            runner.backlog = {"priority_order": ["security"], "tasks": [
                {"id": "UNAPPROVED", "authorized": True, "status": "pending", "category": "security"},
                {"id": "DEV-SMOKE-001", "authorized": False, "status": "pending", "category": "security"}]}
            self.assertIsNone(runner.select_task())
            runner.backlog["tasks"][1]["authorized"] = True
            self.assertEqual(runner.select_task()["id"], "DEV-SMOKE-001")
            (Path(temporary) / "task-state.json").write_text(json.dumps({"DEV-SMOKE-001": {"status": "cancelled"}}), encoding="utf-8")
            self.assertIsNone(runner.select_task())

    def test_worker_environments_do_not_inherit_provider_credentials(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "SYNTHETIC_TEST_ONLY", "ANTHROPIC_API_KEY": "SYNTHETIC_TEST_ONLY",
                                     "NPM_TOKEN": "SYNTHETIC_TEST_ONLY", "GMAIL_TOKEN": "SYNTHETIC_TEST_ONLY"}):
            for keep_auth in (True, False):
                env = clean_environment(keep_auth_transport=keep_auth)
                self.assertFalse(any(key in env for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NPM_TOKEN", "GMAIL_TOKEN")))

    def test_ide_bridge_blocks_unadvertised_mutations_even_with_raw_rpc(self):
        for name in ("agent_execute", "agent_spawn", "autopilot_enable", "swarm_init", "run_shell", "memory_store"):
            with self.subTest(name=name):
                self.assertFalse(permitted({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name}}))
        self.assertTrue(permitted({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "agent_list"}}))
        self.assertTrue(permitted({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "jarvis_development_status"}}))
        self.assertFalse(permitted({"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {"uri": "file:///private"}}))

    def test_nested_mcp_results_preserve_disabled_state_and_errors(self):
        inner = {"content": [{"type": "text", "text": json.dumps({"enabled": False, "iterations": 0})}]}
        wrapped = {"content": [{"type": "text", "text": json.dumps(inner)}]}
        self.assertEqual(decode_tool_result(wrapped), {"enabled": False, "iterations": 0})
        with self.assertRaises(RuntimeError):
            decode_tool_result({"content": [{"type": "text", "text": "error"}], "isError": True})

    @unittest.skipUnless(os.name == "nt", "native MXC and Job Objects require Windows")
    def test_native_canaries_and_owned_stop_are_enforced(self):
        from development.orchestrator.preflight import verify_sandbox, verify_stop
        from development.orchestrator.windows_job import WindowsJob
        with WindowsJob() as job:
            result = verify_sandbox(job)
            self.assertTrue(result["passed"], result)
            self.assertEqual(job.sample()["cpu_rate_percent"], 25)
            self.assertEqual(job.sample()["memory_limit_mib"], 8192)
        self.assertTrue(verify_stop()["passed"])
