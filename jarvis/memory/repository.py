"""Conversation, preferences and task records have distinct storage APIs."""

import json
from uuid import uuid4
from datetime import datetime, timezone

from jarvis.core.models import Message
from jarvis.memory.database import Database


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, database: Database):
        self.database = database

    def add_message(self, role: str, content: str) -> None:
        with self.database.connection() as connection:
            connection.execute("INSERT INTO messages(role, content, created_at) VALUES (?, ?, ?)",
                               (role, content, now()))

    def messages(self, limit: int = 200) -> list[Message]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT role, content, created_at FROM (SELECT * FROM messages ORDER BY id DESC LIMIT ?) ORDER BY id",
                (limit,),
            ).fetchall()
        return [Message(**dict(row)) for row in rows]

    def create_task(self, task_id: str, kind: str, request: str = "") -> None:
        stamp = now()
        with self.database.connection() as connection:
            connection.execute("INSERT INTO tasks(id,kind,status,created_at,updated_at,request_original) VALUES (?, ?, 'running', ?, ?, ?)",
                               (task_id, kind, stamp, stamp, request))

    def set_task_status(self, task_id: str, status: str) -> None:
        with self.database.connection() as connection:
            connection.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (status, now(), task_id))

    def tasks(self, limit: int = 50) -> list[dict]:
        with self.database.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
            )]

    def preferences(self) -> dict:
        with self.database.connection() as connection:
            return {row["key"]: json.loads(row["value_json"]) for row in connection.execute("SELECT * FROM preferences")}

    def save_preferences(self, reduced_motion: bool, log_level: str, voice: dict | None = None) -> None:
        if type(reduced_motion) is not bool or log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ValueError("Preferenze non valide.")
        with self.database.connection() as connection:
            connection.executemany("INSERT INTO preferences VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                                   [("reduced_motion", json.dumps(reduced_motion)), ("log_level", json.dumps(log_level))])
            if voice is not None:
                from jarvis.infrastructure.settings import validate_voice
                validate_voice(voice)
                connection.execute("INSERT INTO preferences VALUES ('voice', ?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                                   (json.dumps(voice),))

    def finish_task(self, task_id: str, result: str = "", error: str = "") -> None:
        with self.database.connection() as connection:
            connection.execute("UPDATE tasks SET result_text=?, error_text=? WHERE id=?", (result, error, task_id))

    def begin_operation(self, task_id: str, tool: str, arguments: dict) -> str:
        operation_id = uuid4().hex
        # Current tools only accept identifiers, search text and limits. Unknown future
        # parameters are redacted by default rather than persisted as credentials.
        safe = {key: value if key in {"application_id", "query", "limit", "site_id"} else "[REDACTED]"
                for key, value in arguments.items()}
        with self.database.connection() as connection:
            connection.execute("INSERT INTO operations(id,task_id,tool,arguments_json,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                               (operation_id, task_id, tool, json.dumps(safe, ensure_ascii=False), "attempted", now(), now()))
        return operation_id

    def operation_status(self, operation_id: str, status: str, result: str = "", evidence: dict | None = None, error: str = "") -> None:
        with self.database.connection() as connection:
            connection.execute("UPDATE operations SET status=?,updated_at=?,result_text=?,evidence_json=?,error_text=? WHERE id=?",
                               (status, now(), result, json.dumps(evidence or {}, ensure_ascii=False), error, operation_id))

    def operations(self, query: str = "", limit: int = 20) -> list[dict]:
        # Literal LIKE matching, never interpreted as SQL or model instructions.
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT o.*, t.request_original FROM operations o JOIN tasks t ON t.id=o.task_id "
                "WHERE t.request_original LIKE ? ESCAPE '\\' OR o.tool LIKE ? ESCAPE '\\' "
                "OR o.result_text LIKE ? ESCAPE '\\' ORDER BY o.created_at DESC LIMIT ?",
                (f"%{escaped}%",) * 3 + (max(1, min(limit, 50)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def clear_history(self, active_task_id: str) -> None:
        with self.database.connection() as connection:
            connection.execute("PRAGMA secure_delete = ON")
            connection.execute("DELETE FROM messages")
            connection.execute("DELETE FROM tasks WHERE id != ?", (active_task_id,))
        with self.database.connection() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def clear_preferences(self) -> None:
        with self.database.connection() as connection:
            connection.execute("PRAGMA secure_delete = ON")
            connection.execute("DELETE FROM preferences")

    def snapshot(self) -> dict:
        return {"messages": self.messages(), "tasks": self.tasks(), "preferences": self.preferences(), "operations": self.operations()}
