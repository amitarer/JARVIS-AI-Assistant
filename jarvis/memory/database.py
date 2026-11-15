"""Short-lived SQLite connections, transactions and versioned migration."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=2.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > 2:
                raise RuntimeError("Database creato da una versione JARVIS più recente.")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA secure_delete = ON")
            for target, filename in ((1, "001_initial.sql"), (2, "002_operation_audit.sql")):
                if version >= target:
                    continue
                migration = Path(__file__).parent / "migrations" / filename
                connection.executescript("BEGIN IMMEDIATE;\n" + migration.read_text(encoding="utf-8") + "\nCOMMIT;")
            # Interrupted executions from an earlier session must not remain active.
            connection.execute(
                "UPDATE tasks SET status='interrupted' WHERE status IN ('running', 'waiting_approval')"
            )
            connection.execute("UPDATE operations SET status='interrupted' WHERE status IN ('attempted', 'executing')")
