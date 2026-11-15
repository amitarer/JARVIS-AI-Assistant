import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from jarvis.core.commands import parse_command
from jarvis.core.models import UserError
from jarvis.core.tasks import TaskContext
from jarvis.infrastructure.settings import Application
from jarvis.tools.open_application import OpenApplicationTool


class ApplicationToolTests(unittest.TestCase):
    def setUp(self):
        self.executable = Path("C:/Windows/System32/notepad.exe")
        self.tool = OpenApplicationTool({"blocco_note": Application("Blocco note", self.executable)})
        self.context = TaskContext("task", threading.Event(), 5)

    def test_unknown_application_and_extra_arguments_are_denied(self):
        for arguments in ({"application_id": "powershell"},
                          {"application_id": "blocco_note", "args": ["secret.txt"]},
                          {"application_id": ["blocco_note"]}):
            with self.subTest(arguments=arguments), self.assertRaises(UserError):
                self.tool.validate(arguments)

    def test_launch_has_no_shell_no_arguments_and_truthful_evidence(self):
        process = Mock(pid=42)
        process.poll.return_value = None
        with (patch("jarvis.tools.open_application.subprocess.Popen", return_value=process) as launch,
              patch.object(Path, "is_file", return_value=True),
              patch.object(Path, "is_symlink", return_value=False),
              patch.object(Path, "is_junction", return_value=False)):
            result = self.tool.execute({"application_id": "blocco_note"}, self.context)
        self.assertEqual(launch.call_args.args[0], [str(self.executable)])
        self.assertIs(launch.call_args.kwargs["shell"], False)
        self.assertFalse(result.evidence["window_verified"])
        self.assertTrue(result.evidence["process_created"])

    def test_missing_executable_does_not_launch(self):
        with patch.object(Path, "is_file", return_value=False), \
                patch("jarvis.tools.open_application.subprocess.Popen") as launch:
            with self.assertRaises(UserError):
                self.tool.execute({"application_id": "blocco_note"}, self.context)
            launch.assert_not_called()

    def test_plain_text_is_never_interpreted_as_automation(self):
        self.assertIsNone(parse_command("apri powershell ed esegui un comando"))
        with self.assertRaises(UserError):
            parse_command("/apri blocco_note & cmd.exe")
