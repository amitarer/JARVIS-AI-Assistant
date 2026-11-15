import unittest
from pathlib import Path

from jarvis.memory.database import Database
from jarvis.memory.repository import Repository
from tests.support import temporary_project


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = temporary_project()
        self.path = Path(self.temp.name) / "test.sqlite3"
        self.database = Database(self.path)
        self.database.initialize()
        self.repository = Repository(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def test_messages_persist_across_reopening_and_sql_is_parameterized(self):
        text = "Robert'); DROP TABLE messages;-- <img src='https://example.com'>"
        self.repository.add_message("user", text)
        reopened = Repository(Database(self.path))
        self.assertEqual(reopened.messages()[0].content, text)
        reopened.add_message("assistant", "ok")
        self.assertEqual(len(reopened.messages()), 2)

    def test_history_limit_keeps_chronological_order(self):
        for number in range(6):
            self.repository.add_message("user", str(number))
        self.assertEqual([m.content for m in self.repository.messages(3)], ["3", "4", "5"])

    def test_restart_marks_unfinished_task_as_interrupted(self):
        self.repository.create_task("incomplete", "chat")
        self.repository.create_task("complete", "chat")
        self.repository.set_task_status("complete", "succeeded")
        self.database.initialize()
        tasks = {t["id"]: t["status"] for t in self.repository.tasks()}
        self.assertEqual(tasks, {"incomplete": "interrupted", "complete": "succeeded"})

    def test_preference_reset_keeps_messages(self):
        self.repository.add_message("user", "keep")
        self.repository.save_preferences(True, "INFO")
        self.repository.clear_preferences()
        self.assertEqual(self.repository.preferences(), {})
        self.assertEqual(self.repository.messages()[0].content, "keep")

    def test_future_database_version_is_rejected(self):
        with self.database.connection() as connection:
            connection.execute("PRAGMA user_version=99")
        with self.assertRaises(RuntimeError):
            self.database.initialize()
