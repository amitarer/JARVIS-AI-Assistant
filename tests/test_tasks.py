import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis.core.models import Cancelled, TaskTimeout
from jarvis.core.tasks import TaskContext
from tests.support import make_controller, temporary_project


class TaskTests(unittest.TestCase):
    def test_deadline_and_cancellation(self):
        context = TaskContext("task", threading.Event(), -1)
        with self.assertRaises(TaskTimeout):
            context.checkpoint()
        context.cancellation.set()
        with self.assertRaises(Cancelled):
            context.checkpoint()

    def test_demo_chat_does_not_run_an_application(self):
        with temporary_project() as directory:
            controller = make_controller(Path(directory))
            events = []
            with patch("jarvis.tools.open_application.subprocess.Popen") as launch:
                controller.run({"kind": "chat", "text": "apri Blocco note"}, threading.Event(), events.append, lambda *_: None)
                launch.assert_not_called()
            messages = controller.repository.messages()
            self.assertEqual(messages[0].role, "user")
            self.assertIn("Nessun modello AI", messages[1].content)
            self.assertEqual(controller.repository.tasks()[0]["status"], "succeeded")

    def test_error_is_reported_and_persisted_without_crashing(self):
        with temporary_project() as directory:
            controller = make_controller(Path(directory))
            events = []
            controller.run({"kind": "chat", "text": "/apri non_autorizzata"}, threading.Event(), events.append, lambda *_: None)
            self.assertEqual(controller.repository.tasks()[0]["status"], "failed")
            self.assertTrue(any(event.kind == "notice" and "non autorizzata" in event.data for event in events))

    def test_stopped_request_has_no_side_effect(self):
        with temporary_project() as directory:
            controller = make_controller(Path(directory))
            cancellation = threading.Event()
            cancellation.set()
            controller.run({"kind": "chat", "text": "/apri blocco_note"}, cancellation, lambda *_: None, lambda *_: None)
            self.assertEqual(controller.repository.messages(), [])

    def test_failure_to_record_an_error_does_not_escape_the_worker(self):
        with temporary_project() as directory:
            controller = make_controller(Path(directory))
            events = []
            with patch.object(controller.repository, "set_task_status", side_effect=OSError("sensitive storage detail")):
                controller.run({"kind": "chat", "text": "/invalid"}, threading.Event(), events.append, lambda *_: None)
            self.assertTrue(any(event.kind == "notice" and "Comando non valido" in event.data for event in events))
            self.assertFalse(any("sensitive storage detail" in str(event.data) for event in events))
