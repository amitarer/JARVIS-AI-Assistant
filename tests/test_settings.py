import json
import logging
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis.bootstrap import ensure_local_data
from jarvis.infrastructure.logging_setup import JsonFormatter
from jarvis.infrastructure.settings import load_settings
from tests.support import populate, temporary_project


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = temporary_project()
        self.root = Path(self.temp.name)
        populate(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_project_env_is_loaded_without_mutating_process_environment(self):
        (self.root / ".env").write_text("JARVIS_REDUCED_MOTION=true\nJARVIS_LOG_LEVEL=WARNING\n", encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            settings = load_settings(self.root)
            self.assertTrue(settings.reduced_motion)
            self.assertEqual(settings.log_level, "WARNING")
            self.assertNotIn("JARVIS_LOG_LEVEL", os.environ)

    def test_environment_overrides_project_dotenv(self):
        (self.root / ".env").write_text("JARVIS_LOG_LEVEL=DEBUG", encoding="utf-8")
        with patch.dict(os.environ, {"JARVIS_LOG_LEVEL": "ERROR"}):
            self.assertEqual(load_settings(self.root).log_level, "ERROR")

    def test_bad_configuration_fails_closed(self):
        with patch.dict(os.environ, {"JARVIS_REDUCED_MOTION": "yes-please"}):
            with self.assertRaises(ValueError):
                load_settings(self.root)

    def test_relative_and_shell_executables_are_rejected(self):
        for executable in ("relative.exe", "C:\\Windows\\System32\\cmd.exe", "C:\\Temp\\script.bat"):
            with self.subTest(executable=executable):
                (self.root / "config/applications.json").write_text(json.dumps({"bad": {
                    "label": "Bad", "executable": executable}}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_settings(self.root)

    def test_data_redirection_is_rejected(self):
        settings = load_settings(self.root)
        with patch.object(Path, "is_junction", return_value=True):
            with self.assertRaises(ValueError):
                ensure_local_data(settings)

    def test_application_aliases_are_validated_as_literal_names(self):
        for aliases in ("chrome", [""], [123], ["chrome\ncommand"]):
            with self.subTest(aliases=aliases):
                (self.root / "config/applications.json").write_text(json.dumps({"browser": {
                    "label": "Browser", "executable": r"C:\Apps\browser.exe", "aliases": aliases}}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_settings(self.root)

    def test_logs_omit_sensitive_extras_and_exception_message(self):
        record = logging.LogRecord("jarvis", logging.ERROR, "", 0, "task_failed", (), None)
        record.task_id = "123"
        record.secret = "DO_NOT_LOG"
        record.arguments = {"password": "DO_NOT_LOG"}
        output = JsonFormatter().format(record)
        self.assertNotIn("DO_NOT_LOG", output)
        self.assertEqual(json.loads(output)["task_id"], "123")
